"""
RPA Orchestration System - Main Orchestrator
-------------------------------------------
Main orchestrator server for managing RPA automation jobs.
Enhanced to include change request data in external reports.
"""
import time
import os
import json
import logging
import datetime
import uuid
from pathlib import Path
from typing import List, Optional, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import traceback

# Import local modules
from auth import check_permission
import auth
from rate_limiter import rate_limit_middleware
import models

from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import ssl

import requests
from fastapi import FastAPI, Depends, HTTPException, status, APIRouter, BackgroundTasks, Query, Path as FastAPIPath, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, validator
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from contextlib import asynccontextmanager

# Import local modules
from config import Config
import db
import auth
from health_reporter import HealthReporter

def send_health_report():
    """Send health report to OGGIES_LOG via ORDS."""
    if not Config.HEALTH_REPORT_ENABLED:
        return
    
    try:
        reporter = HealthReporter(
            endpoint=Config.HEALTH_REPORT_ENDPOINT,
            server_type="Orchestrator",
            db_path=Config.DB_PATH
        )
        
        if reporter.send():
            logger.info("Health report sent successfully")
    except Exception as e:
        logger.error(f"Error sending health report: {str(e)}")

# Setup directories
Config.setup_directories()

# Configure logging
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Config.get_log_path())
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Using data directory: {os.path.abspath(Config.BASE_DATA_DIR)}")
logger.info(f"Using logs directory: {os.path.abspath(Config.LOG_DIR)}")

# Initialize core components
def initialize_app_components():
    """Initialize application components before FastAPI starts."""
    logger.info("Initializing application components...")
    
    if not db.init_db():
        logger.error("Failed to initialize database")
        return False
    
    if not auth.create_default_admin():
        logger.error("Failed to create default admin user")
        return False
    
    job_count = reset_and_configure_scheduler()
    logger.info(f"Configured scheduler with {job_count} jobs")
        
    logger.info("Application components initialized successfully")
    return True

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown events."""
    try:
        app.state.start_time = datetime.datetime.now(datetime.UTC)
        app.state.initialized = initialize_app_components()
        
        if not app.state.initialized:
            logger.error("Application initialization failed")
        
        yield
        
        logger.info("Shutting down RPA Orchestrator...")
        
        if scheduler.running:   
            scheduler.shutdown()
            logger.info("Scheduler shutdown complete")
            
        worker_pool.shutdown(wait=False)
        db.SessionLocal.remove()
        db.engine.dispose()
        
        logger.info("Graceful shutdown completed")
    except Exception as e:
        logger.error(f"Error during startup/shutdown: {str(e)}")
        traceback.print_exc()
        yield

# Initialize FastAPI app
app = FastAPI(
    title="RPA Orchestration System",
    description="API for managing RPA automation jobs",
    version="1.0.0",
    lifespan=lifespan)
    
# Import error handlers
from errors import (
    global_exception_handler, 
    http_exception_handler,
    validation_error_handler
)
app.add_exception_handler(Exception, global_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(ValueError, validation_error_handler)

# SSL Context function
def get_ssl_context():
    if Config.DEVELOPMENT_MODE:
        return None
    
    if not Config.SSL_CERT_PATH or not Config.SSL_KEY_PATH:
        logger.warning("SSL certificate paths not configured, running without SSL")
        return None
        
    if not os.path.exists(Config.SSL_CERT_PATH) or not os.path.exists(Config.SSL_KEY_PATH):
        logger.warning(f"SSL certificate files not found: {Config.SSL_CERT_PATH}, {Config.SSL_KEY_PATH}")
        return None
        
    try:
        context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(Config.SSL_CERT_PATH, Config.SSL_KEY_PATH)
        context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS')
        return context
    except Exception as e:
        logger.error(f"Failed to create SSL context: {str(e)}")
        return None

# Initialize thread pool and scheduler
worker_pool = ThreadPoolExecutor(max_workers=Config.MAX_WORKERS)

scheduler = BackgroundScheduler(
    jobstores={
        'default': SQLAlchemyJobStore(url=f'sqlite:///{Config.DB_PATH}')
    },
    executors={
        'default': {'type': 'threadpool', 'max_workers': 5}
    },
    job_defaults={
        'coalesce': False,
        'max_instances': 3
    }
)

# Define models
class JobBase(BaseModel):
    provider: str
    action: str
    parameters: Dict[str, Any]
    priority: int = Field(default=0, ge=0, le=10)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=Config.MAX_RETRY_ATTEMPTS, ge=0, le=10)

class JobCreate(JobBase):
    pass

class Job(JobBase):
    id: int
    external_job_id: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    scheduled_for: Optional[datetime.datetime] = None
    started_at: Optional[datetime.datetime] = None
    completed_at: Optional[datetime.datetime] = None
    result: Optional[Dict[str, Any]] = None
    evidence: Optional[List[str]] = None
    assigned_worker: Optional[str] = None

class JobStatusUpdate(BaseModel):
    status: str
    result: Optional[Dict[str, Any]] = None
    evidence: Optional[List[str]] = None

class SystemStatus(BaseModel):
    status: str
    uptime: str
    queued_jobs: int
    running_jobs: int
    completed_jobs: int
    failed_jobs: int
    workers: Dict[str, str]
    version: str = "1.0.0"

# Scheduler functions
def poll_job_queue():
    """Poll the job queue for pending jobs and dispatch them to workers in parallel."""
    logger.info("POLLING JOB QUEUE - FUNCTION CALLED")
    try:
        batch_size = Config.BATCH_SIZE
        pending_jobs = db.get_pending_jobs(limit=batch_size)
        logger.info(f"Found {len(pending_jobs)} pending jobs")

        for job in pending_jobs:
            worker_pool.submit(dispatch_job, job)
            logger.info(f"Dispatched job {job['id']} to worker pool")
    except Exception as e:
        logger.error(f"Error polling job queue: {str(e)}")
        traceback.print_exc()
 
def dispatch_job(job):
    """Dispatch a job to a worker with improved error handling."""
    try:
        lock_id = str(uuid.uuid4())
        job_id = job['id']
        
        if not db.acquire_job_lock(job_id, lock_id):
            logger.warning(f"Could not acquire lock for job {job_id}, it may be in progress")
            return
        
        try:
            if not Config.WORKER_ENDPOINTS:
                logger.error(f"No worker endpoints configured. Cannot dispatch job {job_id}")
                db.release_job_lock(job_id, lock_id, "error")
                db.update_job_status(
                    job_id, 
                    "error", 
                    result={"error": "No worker endpoints configured"}
                )
                return
            
            # Check for responsive workers
            available_workers = []
            for endpoint in Config.WORKER_ENDPOINTS:
                status_endpoint = endpoint.replace("/execute", "/health")
                try:
                    response = requests.get(status_endpoint, timeout=5)
                    if response.status_code == 200:
                        available_workers.append(endpoint)
                except Exception:
                    continue
            
            if not available_workers:
                logger.warning(f"No responsive workers found, using round-robin on all workers")
                worker_index = job_id % len(Config.WORKER_ENDPOINTS)
                worker_endpoint = Config.WORKER_ENDPOINTS[worker_index]
            else:
                worker_index = job_id % len(available_workers)
                worker_endpoint = available_workers[worker_index]
                
            logger.info(f"Selected worker endpoint for job {job_id}: {worker_endpoint}")
            
            db.update_job_status(
                job_id, 
                "dispatching", 
                assigned_worker=worker_endpoint
            )
            
            # Create job request
            parameters = job["parameters"].copy()
            if "external_job_id" not in parameters and job.get("external_job_id"):
                parameters["external_job_id"] = job["external_job_id"]

            job_request = {
                "job_id": job_id,
                "provider": job["provider"],
                "action": job["action"],
                "parameters": parameters
            }
            
            try:
                logger.info(f"Dispatching job {job_id} to worker: {worker_endpoint}")
                execute_job_on_worker(job_request, worker_endpoint, lock_id)
            except Exception as e:
                logger.error(f"Error executing job {job_id} on worker: {str(e)}")
                handle_job_error(job_id, str(e), lock_id)
        except Exception as e:
            db.release_job_lock(job_id, lock_id, "error")
            logger.error(f"Error in dispatch job processing: {str(e)}")
            raise
    except Exception as e:
        logger.error(f"Error in dispatch_job for job {job['id']}: {str(e)}")
        logger.error(traceback.format_exc())

@retry(
    stop=stop_after_attempt(Config.MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
def execute_job_on_worker(job_request, worker_endpoint, lock_id):
    """Execute a job on a worker node with retry."""
    try:
        db.update_job_status(job_request["job_id"], "running")
        job_id = job_request["job_id"]
        
        headers = {"Content-Type": "application/json"}
        response = requests.post(
            worker_endpoint,
            json=job_request,
            headers=headers,
            timeout=Config.WORKER_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            
            # Extract screenshots if present
            screenshot_data = []
            if isinstance(result, dict) and isinstance(result.get("result"), dict):
                screenshot_data = result.get("result", {}).get("screenshot_data", [])
                
                if screenshot_data:
                    logger.info(f"Found {len(screenshot_data)} screenshots for job {job_id}")
            
            # Check for error status from worker
            if result.get("status") == "error":
                error_result = result.get("result", {})
                
                db.update_job_status(
                    job_id,
                    "failed",
                    result=error_result
                )
                
                if Config.CALLBACK_ENDPOINT:
                    send_external_report(job_id, "failed", error_result)
                
                logger.error(f"Job {job_id} failed: {error_result.get('message', 'No error message')}")
                
                db.release_job_lock(job_id, lock_id, "failed")
                return False
            
            # Process screenshots if available
            if screenshot_data and isinstance(screenshot_data, list) and len(screenshot_data) > 0:
                try:
                    screenshot_count = db.save_screenshots_for_job(job_id, screenshot_data)
                    logger.info(f"Saved {screenshot_count} screenshots for job {job_id}")
                except Exception as screenshot_error:
                    logger.error(f"Error saving screenshots for job {job_id}: {str(screenshot_error)}")
            
            # Check for internal result status
            if isinstance(result.get("result"), dict) and result.get("result", {}).get("status") == "failure":
                failure_result = result.get("result", {})
                
                db.update_job_status(
                    job_id,
                    "failed",
                    result=failure_result
                )
                
                if Config.CALLBACK_ENDPOINT:
                    send_external_report(job_id, "failed", failure_result)
                
                logger.error(f"Job {job_id} failed with internal status 'failure': {failure_result.get('message', 'No message')}")
                
                db.release_job_lock(job_id, lock_id, "failed")
                return False
            
            # Job completed successfully
            success_result = result.get("result", {})
            
            db.update_job_status(
                job_id,
                "completed",
                result=success_result
            )
            
            if Config.CALLBACK_ENDPOINT:
                send_external_report(job_id, "completed", success_result)
            
            logger.info(f"Job {job_id} completed successfully")
            
            db.release_job_lock(job_id, lock_id, "completed")
            return True
            
        else:
            error_result = {
                "error": f"Worker returned {response.status_code}",
                "response": response.text
            }
            
            db.update_job_status(
                job_id,
                "failed",
                result=error_result
            )
            
            if Config.CALLBACK_ENDPOINT:
                send_external_report(job_id, "failed", error_result)
            
            logger.error(f"Job {job_id} failed: {response.status_code} - {response.text}")
            
            db.release_job_lock(job_id, lock_id, "failed")
            return False
            
    except Exception as e:
        logger.error(f"Error executing job {job_request['job_id']}: {str(e)}")
        handle_job_error(job_request["job_id"], str(e), lock_id)
        return False

def handle_job_error(job_id, error_msg, lock_id):
    """Handle job execution error with retry logic."""
    try:
        job = db.get_job(job_id)
        if not job:
            logger.error(f"Cannot find job {job_id} for error handling")
            return
            
        retry_count = job["retry_count"] + 1
        max_retries = job["max_retries"]
        
        if retry_count < max_retries:
            scheduled_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=Config.RETRY_DELAY)
            
            db.update_job_status(
                job_id, 
                "retry_pending", 
                result={"error": error_msg, "retry": retry_count, "max_retries": max_retries}
            )
            
            db.update_job_retry_count(job_id, retry_count)
            db.release_job_lock(job_id, lock_id, "retry_pending")
            
            logger.info(f"Job {job_id} scheduled for retry ({retry_count}/{max_retries})")
        else:
            db.update_job_status(
                job_id,
                "error",
                result={"error": error_msg, "retries_exhausted": True}
            )
            
            db.release_job_lock(job_id, lock_id, "error")
            
            logger.error(f"Job {job_id} failed after {retry_count} retries")
    except Exception as e:
        try:
            db.release_job_lock(job_id, lock_id, "error")
        except:
            pass
        logger.error(f"Error handling job {job_id} failure: {str(e)}")

def collect_metrics():
    """Collect system metrics and store them in the database."""
    try:
        status = get_system_status()
        
        metrics_data = {
            "queued_jobs": status.queued_jobs,
            "running_jobs": status.running_jobs,
            "completed_jobs": status.completed_jobs,
            "failed_jobs": status.failed_jobs,
            "workers": status.workers
        }
        
        db.collect_system_metrics(metrics_data)
        logger.debug("System metrics collected")
    except Exception as e:
        logger.error(f"Error collecting metrics: {str(e)}")

def cleanup_old_evidence():
    """Clean up old evidence files."""
    try:
        retention_days = Config.EVIDENCE_RETENTION_DAYS
        cutoff_date = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=retention_days)
        
        evidence_dir = Path(Config.EVIDENCE_DIR)
        for item in evidence_dir.glob("*"):
            if item.is_dir():
                stats = item.stat()
                last_modified = datetime.datetime.fromtimestamp(stats.st_mtime)
                
                if last_modified < cutoff_date:
                    job_id = item.name.split("_")[1] if "_" in item.name else None
                    if job_id and job_id.isdigit():
                        job = db.get_job(int(job_id))
                        if not job:
                            for file in item.glob("*"):
                                file.unlink()
                            item.rmdir()
                            logger.info(f"Cleaned up old evidence for job {job_id}")
    except Exception as e:
        logger.error(f"Error cleaning up evidence: {str(e)}")

def recover_stale_jobs():
    """Recover jobs with stale locks."""
    try:
        count = db.recover_stale_locks(max_lock_age_minutes=Config.WORKER_TIMEOUT // 60)
        if count > 0:
            logger.info(f"Recovered {count} jobs with stale locks")
    except Exception as e:
        logger.error(f"Error recovering stale jobs: {str(e)}")

def get_system_status():
    """Get current system status."""
    try:
        with db.db_session() as session:
            queued_jobs = session.query(db.JobQueue).filter(db.JobQueue.status == "pending").count()
            running_jobs = session.query(db.JobQueue).filter(db.JobQueue.status.in_(["running", "dispatching"])).count()
            completed_jobs = session.query(db.JobQueue).filter(db.JobQueue.status == "completed").count()
            failed_jobs = session.query(db.JobQueue).filter(db.JobQueue.status.in_(["failed", "error"])).count()
        
        # Check worker status
        workers = {}
        for endpoint in Config.WORKER_ENDPOINTS:
            try:
                status_endpoint = endpoint.replace("/execute", "/status")
                response = requests.get(status_endpoint, timeout=5)
                if response.status_code == 200:
                    workers[endpoint] = "online"
                else:
                    workers[endpoint] = f"error: {response.status_code}"
            except Exception as e:
                workers[endpoint] = f"offline: {str(e)}"
        
        # Calculate uptime
        start_time = getattr(app, "start_time", datetime.datetime.now(datetime.UTC))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=datetime.UTC)
        
        current_time = datetime.datetime.now(datetime.UTC)
        uptime = str(current_time - start_time)
        
        return SystemStatus(
            status="online",
            uptime=uptime,
            queued_jobs=queued_jobs,
            running_jobs=running_jobs,
            completed_jobs=completed_jobs,
            failed_jobs=failed_jobs,
            workers=workers,
            version="0.9.0"
        )
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        return SystemStatus(
            status="degraded",
            uptime="unknown",
            queued_jobs=0,
            running_jobs=0,
            completed_jobs=0,
            failed_jobs=0,
            workers={"error": str(e)},
            version="0.9.0"
        )

def poll_worker_job_status():
    """Poll workers for job status updates."""
    logger.info("Polling workers for job status updates")
    try:
        with db.db_session() as session:
            active_jobs = session.query(db.JobQueue).filter(
                db.JobQueue.status.in_(["running", "dispatching"]),
                db.JobQueue.assigned_worker.isnot(None)
            ).all()
            
            active_jobs = [db.to_dict(job) for job in active_jobs]
        
        logger.info(f"Found {len(active_jobs)} active jobs to check")
        
        for job in active_jobs:
            try:
                job_id = job["id"]
                worker_endpoint = job["assigned_worker"]
                
                if not worker_endpoint:
                    continue
                    
                status_endpoint = worker_endpoint.replace("/execute", f"/status/{job_id}")
                
                logger.info(f"Checking status of job {job_id} on worker {status_endpoint}")
                
                response = requests.get(
                    status_endpoint, 
                    timeout=Config.WORKER_TIMEOUT // 2
                )
                logger.info(f"Worker response structure: {json.dumps(response.json(), default=str)[:500]}")
                if response.status_code == 200:
                    job_status = response.json()
                    
                    if job_status.get("job_id") == job_id:
                        status = job_status.get("status")
                        
                        if status in ["success", "completed"]:
                            db.update_job_status(
                                job_id,
                                "completed", 
                                result=job_status.get("result"),
                                evidence=job_status.get("result", {}).get("evidence")
                            )
                            logger.info(f"Job {job_id} completed successfully via polling")
                            
                        elif status in ["error", "failed"]:
                            db.update_job_status(
                                job_id,
                                "failed",
                                result=job_status.get("result"),
                                evidence=job_status.get("result", {}).get("evidence")
                            )
                            logger.error(f"Job {job_id} failed via polling")
                            
                        elif status == "in_progress":
                            logger.debug(f"Job {job_id} still in progress")
                            
                        elif status == "not_found":
                            logger.warning(f"Job {job_id} not found on worker {worker_endpoint}")
                            if job["retry_count"] < job["max_retries"]:
                                db.update_job_status(
                                    job_id,
                                    "retry_pending",
                                    result={"error": "Job not found on assigned worker"}
                                )
                                db.update_job_retry_count(job_id, job["retry_count"] + 1)
                                logger.info(f"Rescheduled job {job_id} for retry")
                                
                else:
                    logger.warning(f"Error checking job {job_id} status: {response.status_code} - {response.text}")
                
            except requests.RequestException as e:
                logger.error(f"Error polling status for job {job['id']}: {str(e)}")
                
            except Exception as e:
                logger.error(f"Error processing job {job['id']} status: {str(e)}")
                logger.error(traceback.format_exc())
                
    except Exception as e:
        logger.error(f"Error in job status polling: {str(e)}")
        logger.error(traceback.format_exc())

def reset_and_configure_scheduler():
    """Reset the scheduler and create all necessary jobs with proper configuration."""
    global scheduler
    logger.info("Resetting and configuring scheduler...")
    
    if scheduler.running:
        try:
            logger.info("Shutting down existing scheduler...")
            scheduler.shutdown(wait=True)
            logger.info("Scheduler shutdown complete")
        except Exception as e:
            logger.warning(f"Error during scheduler shutdown: {str(e)}")
    
    # Recreate the scheduler
    scheduler = BackgroundScheduler(
        jobstores={
            'default': SQLAlchemyJobStore(url=f'sqlite:///{Config.DB_PATH}')
        },
        executors={
            'default': {'type': 'threadpool', 'max_workers': 5}
        },
        job_defaults={
            'coalesce': True,
            'max_instances': 1
        }
    )
    
    current_time = datetime.datetime.now(datetime.UTC)
    
    # Define required jobs - REMOVED send_system_status_report to stop null API pushes
    jobs_config = [
        {
            "id": "poll_job_queue",
            "func": poll_job_queue,
            "trigger": "interval",
            "seconds": Config.JOB_POLL_INTERVAL,
            "next_run_time": current_time + datetime.timedelta(seconds=5),
            "replace_existing": True
        },
        {
            "id": "collect_metrics",
            "func": collect_metrics,
            "trigger": "interval",
            "seconds": Config.METRICS_INTERVAL,
            "next_run_time": current_time + datetime.timedelta(seconds=15),
            "replace_existing": True
        },
        {
            "id": "cleanup_old_evidence",
            "func": cleanup_old_evidence,
            "trigger": "cron",
            "hour": Config.CLEANUP_HOUR,
            "replace_existing": True
        },
        {
            "id": "recover_stale_jobs",
            "func": recover_stale_jobs,
            "trigger": "interval",
            "minutes": 10,
            "next_run_time": current_time + datetime.timedelta(seconds=30),
            "replace_existing": True
        },
        {
            "id": "send_health_report",
            "func": send_health_report,
            "trigger": "interval",
            "seconds": Config.HEALTH_REPORT_INTERVAL,
            "next_run_time": current_time + datetime.timedelta(seconds=60),
            "replace_existing": True
        },
        {
            "id": "poll_worker_job_status",
            "func": poll_worker_job_status,
            "trigger": "interval",
            "seconds": Config.JOB_POLL_INTERVAL,
            "next_run_time": current_time + datetime.timedelta(seconds=45),
            "replace_existing": True
        }
    ]
    
    # Start with fresh scheduler
    for job_config in jobs_config:
        try:
            scheduler.add_job(**job_config)
            logger.info(f"Added job: {job_config['id']}")
        except Exception as e:
            logger.error(f"Error adding job {job_config['id']}: {str(e)}")
    
    scheduler.start()
    logger.info("Scheduler started successfully")
    
    job_count = len(scheduler.get_jobs())
    logger.info(f"Scheduler configured with {job_count} jobs")
    
    for job in scheduler.get_jobs():
        logger.info(f"Scheduled job: {job.id} - next run at {job.next_run_time}")
    
    return job_count

def determine_oracle_status(action, internal_status, std_data=None):
    """
    FIXED: Determine Oracle status with logical cancellation flow
    Removed nonsensical "Bitstream Delete Released" status
    """
    
    logger.info(f"Determining Oracle status: action={action}, internal_status={internal_status}")
    
    if internal_status != "completed":
        # Job failed
        if action.lower() == "validation":
            return "Bitstream Validation Error"
        elif "cancel" in action.lower():
            return "Bitstream Delete Error"
        else:
            return "Bitstream Processing Error"
    
    # Job completed successfully - check business logic
    if std_data:
        logger.info(f"Oracle status determination: service_found={std_data.get('service_found')}, is_active={std_data.get('is_active')}")
        
        # CRITICAL: Check if service was found first
        if not std_data.get("service_found", False):
            logger.info("Oracle status: Service not found")
            return "Bitstream Not Found"
        
        # Service was found - now check its status in logical order
        
        # 1. Check for pending cancellation requests (highest priority)
        if std_data.get("pending_cease_order") or std_data.get("pending_requests"):
            logger.info("Oracle status: Service has pending cancellation")
            return "Bitstream Cancellation Pending"
        
        # 2. Check for implemented/completed cancellations
        if std_data.get("cancellation_implementation_date"):
            logger.info("Oracle status: Service cancellation has been implemented")
            return "Bitstream Already Cancelled"
        
        # 3. Check if service has cancellation data but is inactive
        if std_data.get("cancellation_captured_id") and not std_data.get("is_active", True):
            logger.info("Oracle status: Service has cancellation data and is not active")
            return "Bitstream Already Cancelled"
        
        # 4. FIXED: If we just submitted a cancellation successfully
        if std_data.get("cancellation_submitted") and std_data.get("cancellation_captured_id"):
            logger.info("Oracle status: Cancellation just submitted - now pending")
            return "Bitstream Cancellation Pending" 
        
        # 5. Service is currently active
        if std_data.get("is_active", False):
            logger.info("Oracle status: Service is currently active")
            return "Bitstream Validated"
        
        # 6. Fallback - service found but has cancellation data
        if std_data.get("cancellation_captured_id"):
            logger.info("Oracle status: Service found with cancellation data - likely cancelled")
            return "Bitstream Already Cancelled"
        
        # 7. Handle Evotel-specific statuses 
        if std_data and std_data.get("service_provider") == "Evotel":
            if std_data.get("verification_status") == "Unverified":
                return "Bitstream Verification Pending"
            elif std_data.get("isp_provisioned") == "No":
                return "Bitstream ISP Provisioning Pending"

        # 8. Service found but status unclear
        logger.info("Oracle status: Service found but unclear status - defaulting to validated")
        return "Bitstream Validated"
    
      
    
    # Final fallback
    logger.warning(f"Could not determine status for action={action}, internal_status={internal_status}")
    return "Bitstream Status Unknown"

def determine_error_status(action, error_type, error_message):
    """Determine appropriate status for failed jobs based on error details."""
    
    if error_type == "TIMEOUT_ERROR":
        if "cancel" in action.lower():
            return "Bitstream Delete Timeout"
        else:
            return "Bitstream Validation Timeout"
    
    elif error_type == "PORTAL_UNRESPONSIVE":
        if "cancel" in action.lower():
            return "Bitstream Delete Portal Error"
        else:
            return "Bitstream Validation Portal Error"
    
    elif error_type == "LOGIN_ERROR":
        if "cancel" in action.lower():
            return "Bitstream Delete Auth Error"
        else:
            return "Bitstream Validation Auth Error"
    
    elif error_type == "NETWORK_ERROR":
        if "cancel" in action.lower():
            return "Bitstream Delete Network Error"
        else:
            return "Bitstream Validation Network Error"
    
    elif error_type == "WEBDRIVER_ERROR":
        if "cancel" in action.lower():
            return "Bitstream Delete System Error"
        else:
            return "Bitstream Validation System Error"
    
    else:
        if "cancel" in action.lower():
            return "Bitstream Delete Error"
        else:
            return "Bitstream Validation Error"

def prepare_external_report_data(job_dict, status, result=None):
    """COMPREHENSIVE: Generate external report with ALL possible data including change requests"""
    
    # DEFENSIVE: Ensure all inputs are valid
    if not job_dict:
        job_dict = {}
    if not isinstance(job_dict, dict):
        job_dict = {}
    if not result:
        result = {}
    if not isinstance(result, dict):
        result = {}
    
    # Extract basic info with safe defaults
    external_job_id = (
        job_dict.get("external_job_id") or 
        (job_dict.get("parameters", {}) or {}).get("external_job_id") or
        f"UNKNOWN_{job_dict.get('id', 'NO_ID')}"
    )
    
    provider = (job_dict.get("provider") or "").upper()
    if not provider:
        provider = "UNKNOWN"
        
    action = job_dict.get("action") or ""
    if not action:
        action = "unknown"
    
    # Format timestamp
    timestamp = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    
    # DEFENSIVE: Standardize result data
    try:
        std_data = standardize_automation_result(result, provider.lower())
        
        if std_data is None:
            logger.error("standardize_automation_result returned None, creating default")
            std_data = {
                "found": False,
                "is_active": False,
                "service_found": False,
                "customer_found": False,
                "customer_is_active": False,
                "standardization_error": "Function returned None"
            }
        elif not isinstance(std_data, dict):
            logger.error(f"standardize_automation_result returned non-dict: {type(std_data)}")
            std_data = {
                "found": False,
                "is_active": False,
                "service_found": False,
                "customer_found": False,
                "customer_is_active": False,
                "standardization_error": f"Function returned {type(std_data)}"
            }
            
    except Exception as e:
        logger.error(f"Error in standardize_automation_result: {str(e)}")
        logger.error(traceback.format_exc())
        std_data = {
            "found": False,
            "is_active": False,
            "service_found": False,
            "customer_found": False,
            "customer_is_active": False,
            "standardization_error": str(e)
        }
    
    # Start building the flat JOB_EVI structure
    job_evi = {}
    
    # Add execution metadata
    job_evi["provider"] = provider
    job_evi["action"] = action
    job_evi["timestamp"] = timestamp
    job_evi["job_internal_id"] = str(job_dict.get("id", ""))
    job_evi["retry_count"] = str(job_dict.get("retry_count", "0"))
    job_evi["max_retries"] = str(job_dict.get("max_retries", "2"))
    job_evi["execution_start"] = str(job_dict.get("started_at", ""))
    job_evi["execution_end"] = str(job_dict.get("updated_at", ""))
    job_evi["assigned_worker"] = str(job_dict.get("assigned_worker", ""))
    job_evi["automation_status"] = "success" if status == "completed" else "failed"
    
    # Add automation message
    if result.get("message"):
        job_evi["automation_message"] = str(result["message"])
    elif std_data.get("found"):
        circuit = std_data.get("circuit_number", "unknown")
        job_evi["automation_message"] = f"Successfully extracted data for circuit {circuit}"
    else:
        job_evi["automation_message"] = "No data found for the specified circuit"
    
    # COMPREHENSIVE DATA EXTRACTION: Add ALL possible data for end-user review
    try:
        # Add ALL standardized data with "evidence_" prefix
        for key, value in std_data.items():
            if value and str(value).strip() and not isinstance(value, (dict, list)):
                job_evi[f"evidence_{key}"] = str(value)
        
        # Add RAW details data for end-user eyeballing
        details = result.get("details", {})
        if details:
            
            # OCTOTEL-SPECIFIC: Add comprehensive Octotel service and customer data + CHANGE REQUESTS
            if provider.lower() == "octotel":
                
                # Extract services data (streamlined format)
                services_data = details.get("services", [])
                if services_data:
                    job_evi["octotel_services_count"] = str(len(services_data))
                    
                    # Process primary service (first one)
                    primary_service = services_data[0]
                    logger.info("OCTOTEL: Processing primary service data for external report")
                    
                    # === SERVICE IDENTIFIERS ===
                    service_identifiers = primary_service.get("service_identifiers", {})
                    if service_identifiers:
                        # Core identifiers
                        if service_identifiers.get("primary_id"):
                            job_evi["octotel_service_primary_id"] = str(service_identifiers["primary_id"])
                        if service_identifiers.get("line_reference"):
                            job_evi["octotel_line_reference"] = str(service_identifiers["line_reference"])
                        
                        # UUIDs (handle lists)
                        service_uuids = service_identifiers.get("service_uuid", [])
                        if service_uuids:
                            if isinstance(service_uuids, list):
                                job_evi["octotel_service_uuid_count"] = str(len(service_uuids))
                                for i, uuid in enumerate(service_uuids[:3]):  # First 3 UUIDs
                                    job_evi[f"octotel_service_uuid_{i}"] = str(uuid)
                            else:
                                job_evi["octotel_service_uuid_0"] = str(service_uuids)
                        
                        line_uuids = service_identifiers.get("line_uuid", [])
                        if line_uuids:
                            if isinstance(line_uuids, list):
                                job_evi["octotel_line_uuid_count"] = str(len(line_uuids))
                                for i, uuid in enumerate(line_uuids[:3]):  # First 3 UUIDs
                                    job_evi[f"octotel_line_uuid_{i}"] = str(uuid)
                            else:
                                job_evi["octotel_line_uuid_0"] = str(line_uuids)
                    
                    # === CUSTOMER INFORMATION ===
                    customer_information = primary_service.get("customer_information", {})
                    if customer_information:
                        job_evi["octotel_customer_fields_count"] = str(len(customer_information))
                        
                        # Customer name
                        if customer_information.get("name"):
                            job_evi["octotel_customer_name"] = str(customer_information["name"])
                        
                        # Customer emails (handle lists)
                        customer_emails = customer_information.get("email", [])
                        if customer_emails:
                            if isinstance(customer_emails, list):
                                job_evi["octotel_customer_email_count"] = str(len(customer_emails))
                                for i, email in enumerate(customer_emails[:3]):  # First 3 emails
                                    job_evi[f"octotel_customer_email_{i}"] = str(email)
                            else:
                                job_evi["octotel_customer_email_0"] = str(customer_emails)
                        
                        # Customer phones (handle lists)
                        customer_phones = customer_information.get("phone", [])
                        if customer_phones:
                            if isinstance(customer_phones, list):
                                job_evi["octotel_customer_phone_count"] = str(len(customer_phones))
                                for i, phone in enumerate(customer_phones[:3]):  # First 3 phones
                                    job_evi[f"octotel_customer_phone_{i}"] = str(phone)
                            else:
                                job_evi["octotel_customer_phone_0"] = str(customer_phones)
                    
                    # === SERVICE DETAILS ===
                    service_details = primary_service.get("service_details", {})
                    if service_details:
                        job_evi["octotel_service_details_count"] = str(len(service_details))
                        
                        # Map all service detail fields
                        service_detail_mapping = {
                            "type": "octotel_service_type",
                            "speed_profile": "octotel_speed_profile", 
                            "start_date": "octotel_start_date",
                            "isp_order_number": "octotel_isp_order_number"
                        }
                        
                        for source_key, target_key in service_detail_mapping.items():
                            value = service_details.get(source_key)
                            if value:
                                job_evi[target_key] = str(value)
                    
                    # === TECHNICAL DETAILS ===
                    technical_details = primary_service.get("technical_details", {})
                    if technical_details:
                        job_evi["octotel_technical_fields_count"] = str(len(technical_details))
                        
                        # Network infrastructure
                        if technical_details.get("network_node"):
                            job_evi["octotel_network_node"] = str(technical_details["network_node"])
                        if technical_details.get("ont_device"):
                            job_evi["octotel_ont_device"] = str(technical_details["ont_device"])
                        
                        # Technical UUIDs (if different from service identifiers)
                        tech_service_uuids = technical_details.get("service_uuid", [])
                        if tech_service_uuids and isinstance(tech_service_uuids, list):
                            job_evi["octotel_tech_service_uuid_count"] = str(len(tech_service_uuids))
                        
                        tech_line_uuids = technical_details.get("line_uuid", [])
                        if tech_line_uuids and isinstance(tech_line_uuids, list):
                            job_evi["octotel_tech_line_uuid_count"] = str(len(tech_line_uuids))
                    
                    # === LOCATION INFORMATION ===
                    location_information = primary_service.get("location_information", {})
                    if location_information:
                        if location_information.get("address"):
                            job_evi["octotel_service_address"] = str(location_information["address"])
                        if location_information.get("detailed_address"):
                            job_evi["octotel_detailed_address"] = str(location_information["detailed_address"])
                    
                    # === STATUS INFORMATION ===
                    status_information = primary_service.get("status_information", {})
                    if status_information:
                        job_evi["octotel_status_fields_count"] = str(len(status_information))
                        
                        # Current status
                        if status_information.get("current_status"):
                            job_evi["octotel_current_status"] = str(status_information["current_status"])
                        
                        # Status flags
                        if status_information.get("has_pending_cancellation"):
                            job_evi["octotel_has_pending_cancellation"] = str(status_information["has_pending_cancellation"])
                        if status_information.get("has_change_requests"):
                            job_evi["octotel_has_change_requests"] = str(status_information["has_change_requests"])
                    
                    # === CHANGE REQUESTS DATA - NEW COMPREHENSIVE EXTRACTION ===
                    change_requests = primary_service.get("change_requests", {})
                    if change_requests:
                        logger.info("OCTOTEL: Processing comprehensive change requests data for external report")
                        
                        # Basic change request flags
                        job_evi["octotel_change_requests_found"] = str(change_requests.get("change_requests_found", False))
                        job_evi["octotel_total_change_requests"] = str(change_requests.get("total_change_requests", 0))
                        job_evi["octotel_change_requests_extraction_successful"] = str(change_requests.get("extraction_successful", False))
                        
                        # Table headers
                        table_headers = change_requests.get("table_headers", [])
                        if table_headers:
                            job_evi["octotel_change_request_headers"] = " | ".join([str(h) for h in table_headers])
                        
                        # Extraction metadata
                        if change_requests.get("extraction_timestamp"):
                            job_evi["octotel_change_requests_extraction_timestamp"] = str(change_requests["extraction_timestamp"])
                        
                        # Raw table text (first 500 chars for debugging)
                        if change_requests.get("raw_table_text"):
                            raw_table_text = str(change_requests["raw_table_text"])
                            job_evi["octotel_change_requests_raw_table_length"] = str(len(raw_table_text))
                            job_evi["octotel_change_requests_raw_table_preview"] = raw_table_text[:500]
                        
                        # First change request (primary/most important)
                        first_change_request = change_requests.get("first_change_request", {})
                        if first_change_request:
                            job_evi["octotel_primary_change_request_id"] = str(first_change_request.get("id", ""))
                            job_evi["octotel_primary_change_request_type"] = str(first_change_request.get("type", ""))
                            job_evi["octotel_primary_change_request_status"] = str(first_change_request.get("status", ""))
                            job_evi["octotel_primary_change_request_due_date"] = str(first_change_request.get("due_date", ""))
                            job_evi["octotel_primary_change_request_requested_by"] = str(first_change_request.get("requested_by", ""))
                            job_evi["octotel_primary_change_request_full_text"] = str(first_change_request.get("full_row_text", ""))
                        
                        # All change requests (up to 5 for comprehensive reporting)
                        all_change_requests = change_requests.get("all_change_requests", [])
                        if all_change_requests:
                            job_evi["octotel_all_change_requests_count"] = str(len(all_change_requests))
                            
                            for i, cr in enumerate(all_change_requests[:5]):  # Limit to first 5
                                prefix = f"octotel_change_request_{i}_"
                                
                                if cr.get("id"):
                                    job_evi[f"{prefix}id"] = str(cr["id"])
                                if cr.get("type"):
                                    job_evi[f"{prefix}type"] = str(cr["type"])
                                if cr.get("status"):
                                    job_evi[f"{prefix}status"] = str(cr["status"])
                                if cr.get("due_date"):
                                    job_evi[f"{prefix}due_date"] = str(cr["due_date"])
                                if cr.get("requested_by"):
                                    job_evi[f"{prefix}requested_by"] = str(cr["requested_by"])
                                if cr.get("full_row_text"):
                                    job_evi[f"{prefix}full_text"] = str(cr["full_row_text"])
                                if cr.get("row_index") is not None:
                                    job_evi[f"{prefix}row_index"] = str(cr["row_index"])
                        
                        # CRITICAL: Add special flags for Oracle status determination
                        if any(cr.get("status", "").lower() == "pending" for cr in all_change_requests):
                            job_evi["octotel_has_pending_change_requests"] = "true"
                            logger.info("OCTOTEL: Found pending change requests - setting flag for Oracle status")
                        
                        if any("cancellation" in cr.get("type", "").lower() for cr in all_change_requests):
                            job_evi["octotel_has_cancellation_requests"] = "true"
                            logger.info("OCTOTEL: Found cancellation requests - setting flag for Oracle status")
                        
                        # Combined critical flag for easy Oracle consumption
                        if (any(cr.get("status", "").lower() == "pending" and "cancellation" in cr.get("type", "").lower() 
                                for cr in all_change_requests)):
                            job_evi["octotel_has_pending_cancellation_requests"] = "true"
                            logger.info("OCTOTEL: Found pending cancellation requests - setting critical flag for Oracle")
                        
                        logger.info(f"OCTOTEL: Added {len([k for k in job_evi.keys() if 'change_request' in k])} change request fields to external report")
                    
                    # === DATA COMPLETENESS ===
                    data_completeness = primary_service.get("data_completeness", {})
                    if data_completeness:
                        # Completeness flags
                        completeness_mapping = {
                            "has_table_data": "octotel_has_table_data",
                            "has_sidebar_data": "octotel_has_sidebar_data", 
                            "has_customer_contact": "octotel_has_customer_contact",
                            "has_technical_uuids": "octotel_has_technical_uuids",
                            "has_change_requests": "octotel_has_change_requests_data",
                            "overall_score": "octotel_completeness_score"
                        }
                        
                        for source_key, target_key in completeness_mapping.items():
                            value = data_completeness.get(source_key)
                            if value is not None:  # Include False values too
                                job_evi[target_key] = str(value)
                
                # === RAW EXTRACTION DATA ===
                raw_extraction = details.get("raw_extraction", {})
                if raw_extraction:
                    logger.info("OCTOTEL: Processing raw extraction data for external report")
                    
                    # Table data count
                    table_data = raw_extraction.get("table_data", [])
                    if table_data:
                        job_evi["octotel_raw_table_rows"] = str(len(table_data))
                        
                        # Add first table row details
                        if len(table_data) > 0:
                            first_row = table_data[0]
                            if isinstance(first_row, dict):
                                if first_row.get("row_text"):
                                    job_evi["octotel_raw_table_row_text"] = str(first_row["row_text"])
                                if first_row.get("extraction_timestamp"):
                                    job_evi["octotel_raw_table_timestamp"] = str(first_row["extraction_timestamp"])
                    
                    # Sidebar data
                    sidebar_data = raw_extraction.get("sidebar_data", {})
                    if sidebar_data:
                        if sidebar_data.get("raw_text"):
                            # Include first 500 chars of raw sidebar text
                            raw_sidebar_text = str(sidebar_data["raw_text"])
                            job_evi["octotel_raw_sidebar_length"] = str(len(raw_sidebar_text))
                            job_evi["octotel_raw_sidebar_preview"] = raw_sidebar_text[:500]
                        
                        if sidebar_data.get("extraction_timestamp"):
                            job_evi["octotel_raw_sidebar_timestamp"] = str(sidebar_data["extraction_timestamp"])
                    
                    # Extraction metadata
                    total_services_scanned = raw_extraction.get("total_services_scanned", 0)
                    matching_services_found = raw_extraction.get("matching_services_found", 0)
                    
                    job_evi["octotel_total_services_scanned"] = str(total_services_scanned)
                    job_evi["octotel_matching_services_found"] = str(matching_services_found)
                
                # === EXTRACTION METADATA ===
                extraction_metadata = details.get("extraction_metadata", {})
                if extraction_metadata:
                    metadata_mapping = {
                        "search_term": "octotel_search_term",
                        "extraction_timestamp": "octotel_extraction_timestamp",
                        "completeness_score": "octotel_final_completeness_score",
                        "processing_approach": "octotel_processing_approach"
                    }
                    
                    for source_key, target_key in metadata_mapping.items():
                        value = extraction_metadata.get(source_key)
                        if value:
                            job_evi[target_key] = str(value)
                
                # === LEGACY COMPATIBILITY FIELDS ===
                # Add backward-compatible fields for existing Oracle consumers
                if services_data:
                    primary_service = services_data[0]
                    
                    # Core service fields
                    service_identifiers = primary_service.get("service_identifiers", {})
                    if service_identifiers.get("line_reference"):
                        job_evi["circuit_number"] = str(service_identifiers["line_reference"])
                    
                    customer_info = primary_service.get("customer_information", {})
                    if customer_info.get("name"):
                        job_evi["customer_name"] = str(customer_info["name"])
                    
                    service_details = primary_service.get("service_details", {})
                    if service_details.get("type"):
                        job_evi["service_type"] = str(service_details["type"])
                    
                    location_info = primary_service.get("location_information", {})
                    if location_info.get("address"):
                        job_evi["service_address"] = str(location_info["address"])
                    
                    status_info = primary_service.get("status_information", {})
                    if status_info.get("current_status"):
                        job_evi["current_status"] = str(status_info["current_status"])
                
                logger.info(f"OCTOTEL: Added {len([k for k in job_evi.keys() if k.startswith('octotel_')])} Octotel-specific fields to external report")

            # OSN-SPECIFIC: Add raw order data (existing code)
            elif provider.lower() == "osn":
                order_data = details.get("order_data", [])
                if order_data:
                    job_evi["raw_order_count"] = str(len(order_data))
                    
                    # Add first 10 orders with full details
                    for i, order in enumerate(order_data[:10]):
                        if isinstance(order, dict):
                            prefix = f"raw_order_{i}_"
                            # Add ALL order fields
                            for order_key, order_value in order.items():
                                if order_value and str(order_value).strip():
                                    job_evi[f"{prefix}{order_key}"] = str(order_value)
                
                # Add service info if available
                service_info = details.get("service_info", {})
                if service_info:
                    for key, value in service_info.items():
                        if value and str(value).strip():
                            job_evi[f"raw_service_{key}"] = str(value)
                
                # Add customer details if available
                customer_details = details.get("customer_details", {})
                if customer_details:
                    for key, value in customer_details.items():
                        if value and str(value).strip():
                            job_evi[f"raw_customer_{key}"] = str(value)
                
                # Add cease order details if available
                cease_order_details = details.get("cease_order_details", [])
                if cease_order_details:
                    job_evi["raw_cease_order_count"] = str(len(cease_order_details))
                    
                    # Add ALL cease order details
                    for i, cease_order in enumerate(cease_order_details):
                        if isinstance(cease_order, dict):
                            prefix = f"raw_cease_order_{i}_"
                            # Add ALL cease order fields
                            for order_key, order_value in cease_order.items():
                                if order_value and str(order_value).strip():
                                    job_evi[f"{prefix}{order_key}"] = str(order_value)
                            
                            # CRITICAL: Make sure requested_cease_date is explicitly added
                            if cease_order.get("requested_cease_date"):
                                job_evi["REQUESTED_CEASE_DATE"] = str(cease_order["requested_cease_date"])
                                job_evi["requested_cancellation_date"] = str(cease_order["requested_cease_date"])
                                logger.info(f"EXTERNAL REPORT: Added requested cease date: {cease_order['requested_cease_date']}")
                
                # Add formatted customer data if available
                formatted_customer_data = details.get("formatted_customer_data", {})
                if formatted_customer_data:
                    for key, value in formatted_customer_data.items():
                        if value and str(value).strip():
                            job_evi[f"formatted_customer_{key.lower().replace(' ', '_')}"] = str(value)
                
                # Add formatted cease order data if available
                formatted_cease_order_data = details.get("formatted_cease_order_data", [])
                if formatted_cease_order_data:
                    for i, cease_order in enumerate(formatted_cease_order_data):
                        if isinstance(cease_order, dict):
                            prefix = f"formatted_cease_order_{i}_"
                            for key, value in cease_order.items():
                                if value and str(value).strip():
                                    field_name = f"{prefix}{key.lower().replace(' ', '_').replace('/', '_')}"
                                    job_evi[field_name] = str(value)
                                    
                                    # CRITICAL: Also check for requested cease date in formatted data
                                    if "requested cease date" in key.lower():
                                        job_evi["FORMATTED_REQUESTED_CEASE_DATE"] = str(value)
                                        logger.info(f"EXTERNAL REPORT: Added formatted requested cease date: {value}")
            
            # MFN-SPECIFIC: Add raw data (existing code)
            elif provider.lower() == "mfn":
                customer_data = details.get("customer_data", {})
                if customer_data:
                    job_evi["raw_mfn_fields_count"] = str(len(customer_data))
                    # Add ALL MFN customer fields
                    for key, value in customer_data.items():
                        if value and str(value).strip():
                            job_evi[f"raw_mfn_{key}"] = str(value)
                
                # Add cancellation data if available
                cancellation_data = details.get("cancellation_data", {})
                if cancellation_data:
                    job_evi["raw_cancellation_found"] = str(cancellation_data.get("found", False))
                    if cancellation_data.get("primary_row"):
                        for key, value in cancellation_data["primary_row"].items():
                            if value and str(value).strip():
                                job_evi[f"raw_cancellation_{key}"] = str(value)

             # EVOTEL-SPECIFIC: Add comprehensive Evotel service and work order data
            elif provider.lower() == "evotel":
                logger.info("EVOTEL: Processing comprehensive service data for external report")
                
                # Extract service summary
                service_summary = details.get("service_summary", {})
                if service_summary:
                    job_evi["evotel_service_found"] = "true"
                    
                    # Map service summary fields
                    service_summary_mapping = {
                        "service_provider": "evotel_service_provider",
                        "product": "evotel_product",
                        "status": "evotel_service_status", 
                        "customer": "evotel_customer_name",
                        "email": "evotel_customer_email",
                        "mobile": "evotel_customer_mobile",
                        "address": "evotel_customer_address",
                        "area": "evotel_customer_area"
                    }
                    
                    for source_key, target_key in service_summary_mapping.items():
                        value = service_summary.get(source_key)
                        if value:
                            job_evi[target_key] = str(value)
                
                # Extract technical details
                technical_details = details.get("technical_details", {})
                if technical_details:
                    job_evi["evotel_technical_fields_count"] = str(len(technical_details))
                    
                    # ONT details
                    ont_details = technical_details.get("ont_details", {})
                    if ont_details:
                        ont_mapping = {
                            "fsan_number": "evotel_fsan_number",
                            "verification": "evotel_verification_status",
                            "port_number": "evotel_port_number",
                            "ports_available": "evotel_ports_available",
                            "active_services": "evotel_active_services"
                        }
                        
                        for source_key, target_key in ont_mapping.items():
                            value = ont_details.get(source_key)
                            if value:
                                job_evi[target_key] = str(value)
                    
                    # ISP details  
                    isp_details = technical_details.get("isp_details", {})
                    if isp_details:
                        for key, value in isp_details.items():
                            if value and str(value).strip():
                                job_evi[f"evotel_isp_{key}"] = str(value)
                
                # Extract work order summary
                work_order_summary = details.get("work_order_summary", {})
                if work_order_summary:
                    job_evi["evotel_total_work_orders"] = str(work_order_summary.get("total_work_orders", 0))
                    job_evi["evotel_primary_work_order_ref"] = str(work_order_summary.get("primary_work_order_reference", ""))
                    job_evi["evotel_primary_work_order_status"] = str(work_order_summary.get("primary_work_order_status", ""))
                    
                    # Extract all work orders
                    all_work_orders = work_order_summary.get("all_work_orders", [])
                    for i, work_order in enumerate(all_work_orders[:5]):  # First 5 work orders
                        if isinstance(work_order, dict):
                            comprehensive_details = work_order.get("comprehensive_details", {})
                            if comprehensive_details:
                                prefix = f"evotel_work_order_{i}_"
                                
                                # Work order header
                                wo_header = comprehensive_details.get("work_order_header", {})
                                if wo_header.get("reference_number"):
                                    job_evi[f"{prefix}reference"] = str(wo_header["reference_number"])
                                
                                # Work order details
                                wo_details = comprehensive_details.get("work_order_details", {})
                                wo_detail_mapping = {
                                    "status": f"{prefix}status",
                                    "isp_provisioned": f"{prefix}isp_provisioned", 
                                    "scheduled_time": f"{prefix}scheduled_time",
                                    "last_comment": f"{prefix}last_comment"
                                }
                                
                                for source_key, target_key in wo_detail_mapping.items():
                                    value = wo_details.get(source_key)
                                    if value:
                                        job_evi[target_key] = str(value)
                
                # Extract comprehensive raw data
                raw_extraction = details.get("raw_extraction", {})
                if raw_extraction:
                    comprehensive_extraction = raw_extraction.get("comprehensive_extraction", {})
                    if comprehensive_extraction:
                        job_evi["evotel_raw_extraction_available"] = "true"
                        
                        # Client details from raw extraction
                        client_details = comprehensive_extraction.get("client_details", {})
                        if client_details:
                            for key, value in client_details.items():
                                if value and str(value).strip():
                                    job_evi[f"evotel_raw_client_{key}"] = str(value)
                        
                        # Service details from raw extraction
                        service_details = comprehensive_extraction.get("service_details", {})
                        if service_details:
                            for key, value in service_details.items():
                                if value and str(value).strip():
                                    job_evi[f"evotel_raw_service_{key}"] = str(value)
                        
                        # ONT number details from raw extraction
                        ont_number_details = comprehensive_extraction.get("ont_number_details", {})
                        if ont_number_details:
                            for key, value in ont_number_details.items():
                                if value and str(value).strip() and not key.endswith("_info"):
                                    job_evi[f"evotel_raw_ont_{key}"] = str(value)
                
                # Extract data completeness metrics
                data_completeness = details.get("data_completeness", {})
                if data_completeness:
                    completeness_mapping = {
                        "overall_completeness_score": "evotel_completeness_score",
                        "successful_sections": "evotel_successful_sections",
                        "total_sections": "evotel_total_sections"
                    }
                    
                    for source_key, target_key in completeness_mapping.items():
                        value = data_completeness.get(source_key)
                        if value is not None:
                            job_evi[target_key] = str(value)
                
                # Legacy compatibility fields
                if service_summary:
                    if service_summary.get("customer"):
                        job_evi["customer_name"] = str(service_summary["customer"])
                    if service_summary.get("product"):
                        job_evi["service_type"] = str(service_summary["product"])
                    if service_summary.get("address"):
                        job_evi["service_address"] = str(service_summary["address"])
                    if service_summary.get("status"):
                        job_evi["current_status"] = str(service_summary["status"])
                
                logger.info(f"EVOTEL: Added {len([k for k in job_evi.keys() if k.startswith('evotel_')])} Evotel-specific fields to external report")

        # Add job parameters for context
        job_params = job_dict.get("parameters", {})
        if job_params:
            for key, value in job_params.items():
                if value and str(value).strip():
                    job_evi[f"job_param_{key}"] = str(value)
        
        # Add automation execution details
        if result.get("details"):
            job_evi["automation_details_available"] = "true"
            if result["details"].get("service_location"):
                job_evi["automation_service_location"] = str(result["details"]["service_location"])
            if result["details"].get("search_successful"):
                job_evi["automation_search_successful"] = str(result["details"]["search_successful"])
            if result["details"].get("data_extraction_successful"):
                job_evi["automation_data_extraction_successful"] = str(result["details"]["data_extraction_successful"])
        
        # Add screenshot count
        if result.get("screenshot_data"):
            job_evi["screenshot_count"] = str(len(result["screenshot_data"]))
        
        # Add evidence files count
        if result.get("evidence"):
            job_evi["evidence_files_count"] = str(len(result["evidence"]))
        
    except Exception as e:
        logger.error(f"Error processing comprehensive data: {str(e)}")
        job_evi["comprehensive_data_error"] = str(e)
    
    # Legacy field for backward compatibility
    if std_data.get("cancellation_captured_id"):
        job_evi["Captured_ID"] = str(std_data["cancellation_captured_id"])
    
    # Use the FIXED determine_oracle_status function
    oracle_status = determine_oracle_status(action, status, std_data)
    
    # Format final report
    report = {
        "JOB_ID": external_job_id,
        "FNO": provider,
        "STATUS": oracle_status,
        "STATUS_DT": timestamp,
        "JOB_EVI": json.dumps(job_evi, default=str)
    }
    
    logger.info(f"Generated Oracle report: JOB_ID={external_job_id}, STATUS={oracle_status}")
    logger.info(f"Report contains {len(job_evi)} data fields for end-user review")
    
    # Log change request specific data if found
    change_request_fields = [k for k in job_evi.keys() if 'change_request' in k]
    if change_request_fields:
        logger.info(f"Included {len(change_request_fields)} change request fields in external report")
    
    return report

def standardize_automation_result(result_data, provider):
    """
    ENHANCED: Convert automation-specific results into a standardized format
    Now properly extracts OSN cease_order_details and customer_details
    AND handles enhanced MFN status data for sophisticated status determination
    """
    # Initialize with default values - NEVER return None
    standardized = {
        "found": False,
        "is_active": False,
        "service_found": False,
        "customer_found": False,
        "customer_is_active": False
    }
    
    # DEFENSIVE: Return early if no result data
    if not result_data or not isinstance(result_data, dict):
        logger.warning("No valid result data provided to standardize_automation_result")
        return standardized
    
    details = result_data.get("details", {})
    
    # Extract cancellation_captured_id from all possible locations
    if "cancellation_captured_id" in result_data:
        standardized["cancellation_captured_id"] = result_data["cancellation_captured_id"]
    elif details.get("cancellation_captured_id"):
        standardized["cancellation_captured_id"] = details["cancellation_captured_id"]
    elif isinstance(details.get("history_data"), dict) and details["history_data"].get("cancellation_captured_id"):
        standardized["cancellation_captured_id"] = details["history_data"]["cancellation_captured_id"]
    
    # Handle Metro Fiber format - ENHANCED with sophisticated status analysis
    if provider.lower() == "mfn":
        logger.info("MFN: Starting enhanced standardization with sophisticated status analysis")
        
        # Check if we have new enhanced data format or old format
        if details.get("service_status_type") is not None:
            # NEW ENHANCED FORMAT: Use the sophisticated status analysis
            logger.info("MFN: Using enhanced data format with detailed status analysis")
            
            # Use the detailed status flags directly
            standardized["found"] = details.get("service_found", False)
            standardized["service_found"] = details.get("service_found", False)
            standardized["customer_found"] = details.get("has_active_service", False)
            standardized["is_active"] = details.get("is_active", False)
            standardized["customer_is_active"] = details.get("is_active", False)
            standardized["service_is_active"] = details.get("is_active", False)
            
            # KEY: Transfer sophisticated flags that drive advanced status determination
            if details.get("pending_cease_order"):
                standardized["pending_cease_order"] = True
                logger.info("MFN: Set pending_cease_order flag - will drive 'Bitstream Cancellation Pending' status")
            
            if details.get("cancellation_implementation_date"):
                standardized["cancellation_implementation_date"] = details["cancellation_implementation_date"]
                logger.info("MFN: Set cancellation_implementation_date - will drive 'Bitstream Already Cancelled' status")
            
            if details.get("cancellation_captured_id"):
                standardized["cancellation_captured_id"] = details["cancellation_captured_id"]
                logger.info(f"MFN: Set cancellation_captured_id: {details['cancellation_captured_id']}")
            
            # Add service status type for debugging
            standardized["service_status_type"] = details.get("service_status_type", "unknown")
            
            # Add customer data with proper prefixes
            customer_data = details.get("customer_data", {})
            if customer_data:
                for key, value in customer_data.items():
                    if value and str(value).strip():
                        standardized[f"customer_{key}"] = str(value)
                        
            logger.info(f"MFN: Enhanced standardization complete - Status type: {standardized.get('service_status_type')}")
            logger.info(f"MFN: Key flags - pending_cease: {standardized.get('pending_cease_order', False)}, " +
                       f"impl_date: {bool(standardized.get('cancellation_implementation_date'))}")
        
        else:
            # LEGACY FORMAT: Fall back to old logic for backward compatibility
            logger.info("MFN: Using legacy data format - applying backward compatibility logic")
            
            # Check active customer data
            customer_data = details.get("customer_data", {})
            if customer_data:
                standardized["customer_found"] = True
                standardized["customer_is_active"] = True
                standardized["found"] = True
                standardized["is_active"] = True
                standardized["service_found"] = True
                
                # FLATTEN ALL CUSTOMER DATA WITH CUSTOMER_ PREFIX
                for key, value in customer_data.items():
                    if value and str(value).strip():  # Only include non-empty values
                        standardized[f"customer_{key}"] = str(value)
            
            # Check deactivated service data
            cancellation_data = details.get("cancellation_data", {})
            if cancellation_data and cancellation_data.get("found"):
                standardized["service_found"] = True
                standardized["found"] = True
                standardized["is_active"] = False
                standardized["service_is_active"] = False
                
                primary_row = cancellation_data.get("primary_row", {})
                if primary_row:
                    # Include cancellation details
                    standardized["primary_id"] = primary_row.get("id", "")
                    standardized["primary_customer_name"] = primary_row.get("customer_name", "")
                    standardized["primary_account_number"] = primary_row.get("account_number", "")
                    standardized["primary_circuit_number"] = primary_row.get("circuit_number", "")
                    standardized["primary_date_time"] = primary_row.get("date_time", "")
                    standardized["primary_record_type"] = primary_row.get("record_type", "")
                    standardized["primary_change_type"] = primary_row.get("change_type", "")
                    standardized["primary_reseller"] = primary_row.get("reseller", "")
                    standardized["primary_activation_date"] = primary_row.get("activation_date", "")
                    
                # Store cancellation_captured_id if present
                if cancellation_data.get("cancellation_captured_id"):
                    standardized["cancellation_captured_id"] = cancellation_data["cancellation_captured_id"]
    
    # Handle Openserve format - ENHANCED WITH CEASE ORDER DETAILS AND CUSTOMER DETAILS
    elif provider.lower() == "osn":
        logger.info("OSN: Starting standardization process")
        
        order_data = details.get("order_data", [])
        service_info = details.get("service_info", {})
        customer_details = details.get("customer_details", {})
        cease_order_details = details.get("cease_order_details", [])  # NEW: Extract cease order details
        
        logger.info(f"OSN: Processing {len(order_data)} orders and {len(cease_order_details)} cease order details")
        
        # Check if we have valid data
        has_valid_data = False
        if order_data and len(order_data) > 0:
            # Check if it's real order data (not just "not found" message)
            first_item = order_data[0]
            if isinstance(first_item, dict):
                if (first_item.get("orderNumber") or 
                    first_item.get("type") or 
                    first_item.get("serviceNumber")):
                    has_valid_data = True
                elif first_item.get("status") == "not_found":
                    has_valid_data = False
                else:
                    has_valid_data = True
        
        # Also check service_info as fallback
        if not has_valid_data and service_info:
            has_valid_data = bool(service_info.get("address") or service_info.get("circuit_number"))
        
        if has_valid_data:
            # Mark as found since we have data
            standardized["found"] = True
            standardized["service_found"] = True
            standardized["customer_found"] = True
            
            logger.info("OSN: Service found - processing orders")
            
            # Process orders with proper cease detection
            cease_orders = []
            implemented_cease_orders = []
            pending_cease_orders = []
            
            for order in order_data:
                if isinstance(order, dict):
                    order_type = str(order.get("type", "")).lower()
                    order_number = order.get("orderNumber", "")
                    
                    # Check if this is a cease order
                    if ("cease" in order_type or 
                        "cancel" in order_type or 
                        order_type == "cease_active_service"):
                        
                        cease_orders.append(order)
                        logger.info(f"OSN: Found cease order {order_number}")
                        
                        # Check implementation status properly
                        date_implemented = order.get("dateImplemented", "")
                        order_status = str(order.get("orderStatus", "")).lower()
                        
                        # Check if implemented
                        is_implemented = False
                        
                        if date_implemented and date_implemented.strip():
                            # Has implementation date
                            logger.info(f"OSN: Cease order {order_number} has implementation date: {date_implemented}")
                            
                            # Check if status indicates completion
                            if order_status in ["accepted", "completed", "implemented", "closed"]:
                                is_implemented = True
                                logger.info(f"OSN: Cease order {order_number} is IMPLEMENTED (date + status)")
                            else:
                                logger.info(f"OSN: Cease order {order_number} has date but status is {order_status}")
                        else:
                            # No implementation date
                            logger.info(f"OSN: Cease order {order_number} has no implementation date")
                            
                            # Check if status alone indicates completion
                            if order_status in ["accepted", "completed", "implemented", "closed"]:
                                is_implemented = True
                                logger.info(f"OSN: Cease order {order_number} is IMPLEMENTED (status only)")
                        
                        # Categorize the order
                        if is_implemented:
                            implemented_cease_orders.append(order)
                            logger.info(f"OSN: Categorized {order_number} as IMPLEMENTED")
                        else:
                            pending_cease_orders.append(order)
                            logger.info(f"OSN: Categorized {order_number} as PENDING")
            
            # Business logic for service status
            if implemented_cease_orders:
                logger.info("OSN: Service has implemented cease orders - CANCELLED")
                standardized["is_active"] = False
                standardized["customer_is_active"] = False
                standardized["service_is_active"] = False
                
                # Get cancellation details from first implemented cease order
                latest_cease = implemented_cease_orders[0]
                standardized["cancellation_implementation_date"] = latest_cease.get("dateImplemented", "")
                standardized["cancellation_captured_id"] = latest_cease.get("orderNumber", "")
                
                logger.info(f"OSN: Cancellation captured ID: {standardized['cancellation_captured_id']}")
                
            elif pending_cease_orders:
                logger.info("OSN: Service has pending cease orders - ACTIVE with pending cancellation")
                standardized["is_active"] = True
                standardized["customer_is_active"] = True
                standardized["service_is_active"] = True
                standardized["pending_cease_order"] = True
                
                # Get pending cancellation details
                pending_order = pending_cease_orders[0]
                standardized["cancellation_captured_id"] = pending_order.get("orderNumber", "")
                
            else:
                logger.info("OSN: Service has no cease orders - ACTIVE")
                standardized["is_active"] = True
                standardized["customer_is_active"] = True
                standardized["service_is_active"] = True
            
            # Add metadata
            standardized["total_orders"] = len(order_data)
            standardized["cease_orders_count"] = len(cease_orders)
            standardized["pending_cease_count"] = len(pending_cease_orders)
            standardized["implemented_cease_count"] = len(implemented_cease_orders)
            
            # NEW: Add ALL customer details with proper prefixes
            if customer_details:
                logger.info("OSN: Extracting detailed customer information")
                for key, value in customer_details.items():
                    if value and str(value).strip():
                        standardized[f"customer_{key}"] = str(value)
                        logger.info(f"OSN: Added customer_{key}: {value}")
            
            # NEW: Add ALL cease order details with proper prefixes
            if cease_order_details:
                logger.info(f"OSN: Extracting {len(cease_order_details)} cease order details")
                for i, cease_order in enumerate(cease_order_details):
                    if isinstance(cease_order, dict):
                        for key, value in cease_order.items():
                            if value and str(value).strip():
                                field_name = f"cease_order_{i}_{key}" if len(cease_order_details) > 1 else f"cease_order_{key}"
                                standardized[field_name] = str(value)
                                logger.info(f"OSN: Added {field_name}: {value}")
                        
                        # CRITICAL: Extract requested_cease_date specifically
                        if cease_order.get("requested_cease_date"):
                            standardized["requested_cease_date"] = str(cease_order["requested_cease_date"])
                            logger.info(f"OSN: REQUESTED CEASE DATE: {cease_order['requested_cease_date']}")
            
            # Add service info
            if service_info:
                if service_info.get("address"):
                    standardized["customer_address"] = service_info["address"]
                if service_info.get("circuit_number"):
                    standardized["customer_circuit_number"] = service_info["circuit_number"]
            
            logger.info(f"OSN: Final standardized result - found={standardized['found']}, is_active={standardized['is_active']}")
        else:
            # No valid data found
            logger.info("OSN: No valid data found")
            standardized["found"] = False
            standardized["service_found"] = False
            standardized["customer_found"] = False
            standardized["is_active"] = False
    
    # Handle Octotel format
    elif provider.lower() == "octotel":
        return standardize_octotel_result(result_data, provider)
    

    # Handle Evotel format - ADD THIS
    elif provider.lower() == "evotel":
        return standardize_evotel_result(result_data, provider)

    # ALWAYS return a valid dictionary
    return standardized

def standardize_octotel_result(result_data, provider):
    """
    Convert Octotel automation results into standardized format
    ALIGNED with MFN/OSN flag patterns for consistent status determination
    """
    # Initialize with default values - NEVER return None  
    standardized = {
        "found": False,
        "is_active": False,
        "service_found": False,
        "customer_found": False,
        "customer_is_active": False,
        
        # ALIGNMENT: Add the same flags that MFN/OSN use for sophisticated status determination
        "pending_cease_order": False,           # For "Bitstream Cancellation Pending"
        "cancellation_implementation_date": None,  # For "Bitstream Already Cancelled"  
        "cancellation_submitted": False,        # For new cancellations
        "cancellation_captured_id": None       # Cancellation reference
    }
    
    # DEFENSIVE: Return early if no result data
    if not result_data or not isinstance(result_data, dict):
        logger.warning("No valid result data provided to standardize_octotel_result")
        return standardized
    
    details = result_data.get("details", {})
    
    # Handle Octotel validation data
    if details.get("found"):
        standardized["found"] = True
        standardized["service_found"] = True
        standardized["customer_found"] = bool(details.get("customer_name"))
        
        # FIXED: Check for pending cancellation in multiple locations
        pending_detected = False
        
        # Method 1: Check top-level pending_requests_detected (legacy support)
        if details.get("pending_requests_detected"):
            pending_detected = True
            logger.info("Octotel: Found pending_requests_detected at top level")
        
        # Method 2: Check within services array for has_pending_cancellation
        services = details.get("services", [])
        if services and isinstance(services, list):
            for service in services:
                status_info = service.get("status_information", {})
                if status_info.get("has_pending_cancellation"):
                    pending_detected = True
                    logger.info("Octotel: Found has_pending_cancellation in service status_information")
                    break
        
        # Method 3: Check top-level has_pending_cancellation (direct field)
        if details.get("has_pending_cancellation"):
            pending_detected = True
            logger.info("Octotel: Found has_pending_cancellation at top level")
        
        # ALIGNMENT: Map any pending cancellation detection to pending_cease_order
        if pending_detected:
            standardized["pending_cease_order"] = True  # → "Bitstream Cancellation Pending"
            standardized["is_active"] = True  # Service exists but has pending requests
            standardized["customer_is_active"] = True
            logger.info("Octotel: Service has pending cancellation requests - mapped to pending_cease_order")
        
        # Determine if service is active based on Octotel's change_request_available flag
        elif details.get("change_request_available"):
            standardized["is_active"] = True
            standardized["customer_is_active"] = True
            standardized["service_is_active"] = True
            logger.info("Octotel: Service is active with change request available")
        else:
            # Check service status for other states
            service_status = details.get("service_status", "").lower()
            if service_status == "cancelled":
                standardized["is_active"] = False
                standardized["service_is_active"] = False
                # ALIGNMENT: Set cancellation implementation date for "Already Cancelled" status
                standardized["cancellation_implementation_date"] = "auto-detected"
                logger.info("Octotel: Service is cancelled - mapped to cancellation_implementation_date")
            elif service_status == "pending":
                standardized["is_active"] = True  # Service exists
                standardized["pending_cease_order"] = True  # Has pending requests → "Cancellation Pending"
                logger.info("Octotel: Service has pending status - mapped to pending_cease_order") 
            else:
                standardized["is_active"] = details.get("change_request_available", False)
        
        # Add Octotel-specific data (preserve existing functionality)
        standardized["customer_name"] = details.get("customer_name", "")
        standardized["service_type"] = details.get("service_type", "")
        standardized["change_request_available"] = details.get("change_request_available", False)
        
        # FIXED: Set pending_requests_detected based on our comprehensive detection
        standardized["pending_requests_detected"] = pending_detected
    
    # ALIGNMENT: Handle cancellation submission results (for cancellation module)
    if details.get("cancellation_submitted"):
        standardized["cancellation_submitted"] = True  # → "Bitstream Cancellation Pending"
        standardized["cancellation_captured_id"] = details.get("release_reference", "")
        standardized["found"] = True  # Service was found to be cancelled
        standardized["service_found"] = True
        logger.info(f"Octotel: Cancellation submitted with reference: {standardized['cancellation_captured_id']}")
        
        # If cancellation was just submitted, service is still active but now has pending cancellation
        if not standardized.get("cancellation_implementation_date"):
            standardized["is_active"] = True  # Service still active until implementation
            standardized["pending_cease_order"] = True  # Now has pending cancellation
    
    logger.info(f"Octotel standardization complete - pending_cease_order: {standardized.get('pending_cease_order')}")
    return standardized

def standardize_evotel_result(result_data, provider):
    """
    Convert Evotel automation results into standardized format
    ALIGNED with MFN/OSN flag patterns for consistent status determination
    UPDATED to handle circuit_number parameter (which maps to Evotel's serial number field internally)
    """
    # Initialize with default values - NEVER return None  
    standardized = {
        "found": False,
        "is_active": False,
        "service_found": False,
        "customer_found": False,
        "customer_is_active": False,
        
        # ALIGNMENT: Add the same flags that MFN/OSN use for sophisticated status determination
        "pending_cease_order": False,           # For "Bitstream Cancellation Pending"
        "cancellation_implementation_date": None,  # For "Bitstream Already Cancelled"  
        "cancellation_submitted": False,        # For new cancellations
        "cancellation_captured_id": None       # Cancellation reference
    }
    
    # DEFENSIVE: Return early if no result data
    if not result_data or not isinstance(result_data, dict):
        logger.warning("No valid result data provided to standardize_evotel_result")
        return standardized
    
    details = result_data.get("details", {})
    
    # Extract main data sections
    service_summary = details.get("service_summary", {})
    work_order_summary = details.get("work_order_summary", {})
    technical_details = details.get("technical_details", {})
    raw_extraction = details.get("raw_extraction", {})
    comprehensive_data = raw_extraction.get("comprehensive_extraction", {})
    
    logger.info("EVOTEL: Starting standardization process")
    
    # Check if we have valid service data
    if service_summary or work_order_summary or comprehensive_data:
        standardized["found"] = True
        standardized["service_found"] = True
        
        # Check if we have customer information
        customer_name = (service_summary.get("customer") or 
                        comprehensive_data.get("client_details", {}).get("client_name"))
        customer_email = (service_summary.get("email") or
                         comprehensive_data.get("client_details", {}).get("email"))
        
        standardized["customer_found"] = bool(customer_name or customer_email)
        
        logger.info(f"EVOTEL: Service found with customer: {standardized['customer_found']}")
        
        # Determine service status using multiple data sources
        service_status = str(service_summary.get("status", "")).lower()
        work_order_status = str(work_order_summary.get("primary_work_order_status", "")).lower()
        
        # Get additional status info from comprehensive data
        service_details = comprehensive_data.get("service_details", {})
        work_order_details = comprehensive_data.get("work_order_details", {})
        
        detailed_service_status = str(service_details.get("service_status", "")).lower()
        detailed_work_order_status = str(work_order_details.get("status", "")).lower()
        
        logger.info(f"EVOTEL: Status analysis - service_status: {service_status}, work_order_status: {work_order_status}")
        logger.info(f"EVOTEL: Detailed status - service: {detailed_service_status}, work_order: {detailed_work_order_status}")
        
        # ALIGNMENT: Status determination logic following MFN/OSN patterns
        
        # 1. Check for active service indicators
        active_indicators = [
            "active" in service_status,
            "provisioned" in work_order_status,
            "completed" in work_order_status,
            "accepted" in work_order_status,
            "active" in detailed_service_status,
            work_order_details.get("isp_provisioned") == "Yes"
        ]
        
        # 2. Check for cancelled/inactive indicators
        cancelled_indicators = [
            "cancelled" in service_status,
            "inactive" in service_status,
            "failed" in work_order_status,
            "cancelled" in detailed_service_status,
            "failed" in detailed_work_order_status
        ]
        
        # 3. Check for pending indicators
        pending_indicators = [
            "pending" in service_status,
            "in progress" in work_order_status,
            "provisioning" in work_order_status,
            "pending" in detailed_service_status,
            "in progress" in detailed_work_order_status,
            work_order_details.get("isp_provisioned") == "No"
        ]
        
        # Apply status logic
        if any(cancelled_indicators):
            logger.info("EVOTEL: Service detected as CANCELLED")
            standardized["is_active"] = False
            standardized["service_is_active"] = False
            standardized["customer_is_active"] = False
            
            # Look for cancellation implementation date
            scheduled_time = work_order_details.get("scheduled_time")
            if scheduled_time:
                standardized["cancellation_implementation_date"] = scheduled_time
                logger.info(f"EVOTEL: Cancellation implementation date: {scheduled_time}")
            else:
                standardized["cancellation_implementation_date"] = "auto-detected"
            
            # Use work order reference as cancellation ID
            work_order_ref = work_order_summary.get("primary_work_order_reference")
            if work_order_ref:
                standardized["cancellation_captured_id"] = work_order_ref
        
        elif any(pending_indicators):
            logger.info("EVOTEL: Service detected as PENDING")
            standardized["is_active"] = True  # Service exists
            standardized["customer_is_active"] = True
            standardized["pending_cease_order"] = True  # Has pending requests
            
            # Use work order reference for tracking
            work_order_ref = work_order_summary.get("primary_work_order_reference")
            if work_order_ref:
                standardized["cancellation_captured_id"] = work_order_ref
        
        elif any(active_indicators) or standardized["customer_found"]:
            logger.info("EVOTEL: Service detected as ACTIVE")
            standardized["is_active"] = True
            standardized["customer_is_active"] = True
            standardized["service_is_active"] = True
        
        else:
            # Default: if we have service data, assume active unless proven otherwise
            logger.info("EVOTEL: Defaulting to ACTIVE status based on data presence")
            standardized["is_active"] = True
            standardized["customer_is_active"] = True
        
        # Extract comprehensive customer information
        client_details = comprehensive_data.get("client_details", {})
        standardized["customer_name"] = (service_summary.get("customer") or 
                                       client_details.get("client_name", ""))
        standardized["customer_email"] = (service_summary.get("email") or
                                        client_details.get("email", ""))
        standardized["customer_mobile"] = (service_summary.get("mobile") or
                                         client_details.get("mobile", ""))
        standardized["customer_address"] = (service_summary.get("address") or
                                          client_details.get("address", ""))
        standardized["customer_area"] = (service_summary.get("area") or
                                       client_details.get("area", ""))
        
        # Extract service information
        standardized["service_type"] = (service_summary.get("product") or
                                      service_details.get("product", ""))
        standardized["service_provider"] = service_details.get("service_provider", "")
        standardized["contract"] = service_details.get("contract", "")
        
        # Extract technical information
        ont_details = technical_details.get("ont_details", {})
        standardized["fsan_number"] = ont_details.get("fsan_number", "")
        standardized["verification_status"] = ont_details.get("verification", "")
        standardized["port_number"] = ont_details.get("port_number", "")
        standardized["ports_available"] = ont_details.get("ports_available", "")
        
        # Extract ISP information
        isp_details = technical_details.get("isp_details", {})
        standardized["isp_reference"] = isp_details.get("reference", "")
        
        # Extract work order information
        standardized["work_order_reference"] = work_order_summary.get("primary_work_order_reference", "")
        standardized["total_work_orders"] = work_order_summary.get("total_work_orders", 0)
        standardized["work_order_status"] = work_order_summary.get("primary_work_order_status", "")
        
        # Add data completeness information
        data_completeness = details.get("data_completeness", {})
        standardized["completeness_score"] = data_completeness.get("overall_completeness_score", 0.0)
        standardized["successful_sections"] = data_completeness.get("successful_sections", 0)
        
        # UPDATED: Handle circuit_number parameter (maps to Evotel's serial number field)
        if result_data.get("circuit_number"):
            standardized["circuit_number"] = result_data["circuit_number"]
            logger.info(f"EVOTEL: Circuit number (mapped from serial): {result_data['circuit_number']}")
        
        # Backward compatibility: Handle legacy serial_number parameter
        elif result_data.get("serial_number"):
            standardized["serial_number"] = result_data["serial_number"]
            standardized["circuit_number"] = result_data["serial_number"]  # Map for uniformity
            logger.info(f"EVOTEL: Legacy serial_number mapped to circuit_number: {result_data['serial_number']}")
        
    else:
        # No service data found
        logger.info("EVOTEL: No service data found")
        standardized["found"] = False
        standardized["service_found"] = False
        standardized["customer_found"] = False
        standardized["is_active"] = False
    
    logger.info(f"EVOTEL: Standardization complete - found={standardized['found']}, is_active={standardized['is_active']}, pending_cease={standardized.get('pending_cease_order', False)}")
    
    return standardized

def send_external_report(job_id, status, result=None):
    """FIXED: Send job status report with comprehensive error handling"""
    
    if not Config.CALLBACK_ENDPOINT:
        logger.debug(f"No callback endpoint configured, skipping external report for job {job_id}")
        return False
       
    try:
        # DEFENSIVE: Get the job details with error handling
        job_dict = db.get_job(job_id)
        if not job_dict:
            logger.error(f"Job {job_id} not found when preparing external report")
            return False
        
        # DEFENSIVE: Ensure result is a dict
        if result is None:
            logger.warning(f"Job {job_id}: result is None, using empty dict")
            result = {}
        elif not isinstance(result, dict):
            logger.warning(f"Job {job_id}: result is not dict (got {type(result)}), converting")
            result = {"original_result": str(result)}
       
        # Use the transformation function to prepare the report data
        report_data = prepare_external_report_data(job_dict, status, result)
        
        # DEFENSIVE: Validate report data
        if not isinstance(report_data, dict):
            logger.error(f"Job {job_id}: prepare_external_report_data returned invalid data")
            return False
        
        # Print for testing/debugging
        print("\n=== EXTERNAL REPORT DATA ===")
        print(json.dumps(report_data, indent=2, default=str))
        print("===========================\n")

        logger.info(f"Job {job_id}: Sending Oracle callback: {json.dumps(report_data, default=str)}")
       
        # Send the report
        response = requests.post(
            Config.CALLBACK_ENDPOINT,
            json=report_data,
            headers={"Content-Type": "application/json"},
            timeout=Config.CALLBACK_TIMEOUT
        )
       
        if response.status_code == 200:
            logger.info(f"Oracle report for job {job_id} sent successfully")
            return True
        else:
            logger.warning(f"Oracle report for job {job_id} failed: {response.status_code} - {response.text}")
            return False
        
    except Exception as e:
        logger.error(f"Error sending Oracle report for job {job_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return False

# API endpoints
@app.post("/token", response_model=auth.Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login and get JWT token."""
    return await auth.login_for_access_token(form_data)

@app.post("/jobs", response_model=Job)
async def create_job_endpoint(
    job: JobCreate,
    background_tasks: BackgroundTasks,
    api_key_info: Dict = Depends(check_permission("job:create"))
):
    """Create a new job."""
    external_job_id = job.parameters.get("external_job_id")
    
    job_dict = db.create_job(
        provider=job.provider,
        action=job.action, 
        parameters=job.parameters,
        external_job_id=external_job_id,
        priority=job.priority,
        retry_count=job.retry_count,
        max_retries=job.max_retries
    )
    
    if job.priority > 5:
        background_tasks.add_task(dispatch_job, job_dict)
    
    return Job(**job_dict)

@app.get("/jobs/{job_id}", response_model=Job)
async def get_job_endpoint(
    job_id: int = FastAPIPath(..., ge=1, title="The ID of the job to get")
):
    """Get job details."""
    job_dict = db.get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if 'status' not in job_dict or job_dict['status'] is None:
        job_dict['status'] = "pending"
        
    return Job(**job_dict)

@app.get("/jobs", response_model=List[Job])
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter jobs by status"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip")
):
    """List jobs with optional filtering."""
    if status:
        jobs = db.get_jobs_by_status(status, limit, offset)
    else:
        with db.db_session() as session:
            query = session.query(db.JobQueue)
            query = query.order_by(db.JobQueue.created_at.desc())
            query = query.limit(limit).offset(offset)
            
            jobs = query.all()
            jobs = [db.to_dict(job) for job in jobs]
        
    return [Job(**job) for job in jobs]

@app.patch("/jobs/{job_id}", response_model=Job)
async def update_job_status_endpoint(
    job_id: int = FastAPIPath(..., ge=1, title="The ID of the job to update"),
    status_update: JobStatusUpdate = None
):
    """Update job status."""
    job_dict = db.get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")
    
    updated_job = db.update_job_status(
        job_id,
        status_update.status,
        result=status_update.result,
        evidence=status_update.evidence
    )
    
    if not updated_job:
        raise HTTPException(status_code=500, detail="Failed to update job status")
    
    return Job(**updated_job)

@app.get("/metrics", response_model=Dict[str, Any])
async def get_metrics():
    """Get system metrics."""
    metrics_data = db.get_recent_metrics(limit=24)
    
    if metrics_data:
        avg_queued = sum(m.get("queued_jobs", 0) for m in metrics_data) / len(metrics_data)
        avg_running = sum(m.get("running_jobs", 0) for m in metrics_data) / len(metrics_data)
        avg_completed = sum(m.get("completed_jobs", 0) for m in metrics_data) / len(metrics_data)
        avg_failed = sum(m.get("failed_jobs", 0) for m in metrics_data) / len(metrics_data)
    else:
        avg_queued = avg_running = avg_completed = avg_failed = 0
    
    current_status = get_system_status()
    return {
        "metrics": metrics_data,
        "averages": {
            "queued_jobs": avg_queued,
            "running_jobs": avg_running,
            "completed_jobs": avg_completed,
            "failed_jobs": avg_failed
        },
        "current": {
            "status": current_status.status,
            "uptime": current_status.uptime,
            "queued_jobs": current_status.queued_jobs,
            "running_jobs": current_status.running_jobs,
            "completed_jobs": current_status.completed_jobs,
            "failed_jobs": current_status.failed_jobs,
            "workers": current_status.workers,
            "version": current_status.version
        }
    }

@app.get("/history/{job_id}", response_model=List[Dict[str, Any]])
async def get_job_history(
    job_id: int = FastAPIPath(..., ge=1, title="The ID of the job to get history for")
):
    """Get job history."""
    job_dict = db.get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        history_data = db.get_job_history(job_id)
        
        if history_data is None:
            history_data = []
            
        return history_data
    except Exception as e:
        logger.error(f"Error retrieving job history: {str(e)}")
        return []

@app.post("/process", response_model=Dict[str, Any])
async def trigger_processing():
    """Manually trigger job processing."""
    poll_job_queue()
    return {"status": "Job processing initiated"}

@app.post("/recover", response_model=Dict[str, Any])
async def recover_stale_jobs_endpoint():
    """Manually trigger recovery of stale jobs."""
    count = db.recover_stale_locks()
    return {"status": "success", "recovered_jobs": count}

@app.get("/jobs/{job_id}/screenshots")
async def get_job_screenshots(
    job_id: int = FastAPIPath(..., ge=1, title="The ID of the job to get screenshots for"),
    include_data: bool = Query(False, description="Whether to include base64 image data")
):
    """Get screenshots associated with a job."""
    job_dict = db.get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")
    
    screenshots = db.get_job_screenshots(job_id, include_data)
    
    return {
        "job_id": job_id,
        "screenshot_count": len(screenshots),
        "screenshots": screenshots
    }

@app.delete("/jobs/{job_id}", response_model=Job)
async def cancel_job(
    job_id: int = FastAPIPath(..., ge=1, title="The ID of the job to cancel")
):
    """Cancel a job if it's still pending or in a cancellable state."""
    job_dict = db.get_job(job_id)
    if not job_dict:
        raise HTTPException(status_code=404, detail="Job not found")
    
    cancellable_statuses = ["pending", "dispatching", "retry_pending", "running"]
    
    if job_dict["status"] not in cancellable_statuses:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot cancel job with status: {job_dict['status']}. "
                   f"Job must be in one of these statuses: {cancellable_statuses}"
        )
    
    cancel_result = {
        "cancelled_by": "user", 
        "cancelled_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "previous_status": job_dict["status"]
    }
    
    updated_job = db.update_job_status(
        job_id, 
        "cancelled", 
        result=cancel_result
    )
    
    if not updated_job:
        raise HTTPException(status_code=500, detail="Failed to cancel job")
    
    if job_dict.get("lock_id"):
        db.release_job_lock(job_id, job_dict["lock_id"], "cancelled")
    
    if Config.CALLBACK_ENDPOINT:
        send_external_report(job_id, "cancelled", cancel_result)
    
    logger.info(f"Job {job_id} cancelled by user")
    return Job(**updated_job)

@app.get("/scheduler", response_model=Dict[str, Any])
async def get_scheduler_status():
    """Get scheduler status and list of scheduled jobs."""
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "function": job.func.__name__,
            "trigger": str(job.trigger),
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None
        })
    
    return {
        "running": scheduler.running,
        "job_count": len(jobs),
        "jobs": jobs
    }

@app.post("/scheduler/reset", response_model=Dict[str, Any])
async def reset_scheduler():
    """Reset and reconfigure the scheduler."""
    job_count = reset_and_configure_scheduler()
    return {
        "status": "success",
        "message": "Scheduler reset and reconfigured successfully",
        "job_count": job_count
    }

# POPIA Compliance Endpoints
@app.post("/privacy/data-request")
async def handle_data_request(request_data: dict):
    """Handle POPIA data subject requests"""
    logger.info(f"POPIA data request received: {request_data}")
    
    return {
        "status": "acknowledged",
        "message": "Data automatically deleted within 30 days of creation",
        "retention_policy": "30 days maximum retention for audit purposes",
        "contact": Config.DATA_PROTECTION_CONTACT,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat()
    }

@app.get("/privacy/notice")
async def privacy_notice():
    """Return privacy notice information"""
    return {
        "purpose": "RPA audit logging and compliance",
        "retention": "30 days maximum",
        "legal_basis": "Legitimate interest for audit compliance",
        "automatic_deletion": True,
        "contact": Config.DATA_PROTECTION_CONTACT,
        "last_updated": "2025-07-03"
    }

@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.datetime.now(datetime.UTC).isoformat()}

def remove_existing_scheduled_jobs():
    """Remove existing scheduled jobs before adding new ones."""
    try:
        from apscheduler.jobstores.base import JobLookupError
        job_ids = ['poll_job_queue', 'collect_metrics', 'cleanup_old_evidence', 'recover_stale_jobs']
        for job_id in job_ids:
            try:
                scheduler.remove_job(job_id)
                logger.info(f"Removed existing scheduled job: {job_id}")
            except JobLookupError:
                pass
        return True
    except Exception as e:
        logger.error(f"Error removing existing scheduled jobs: {str(e)}")
        return False

# Main entry point
if __name__ == "__main__":
    import uvicorn
    
    log_level_name = logging.getLevelName(Config.LOG_LEVEL).lower()
    ssl_context = get_ssl_context()
    
    uvicorn.run(
        app,
        host=Config.ORCHESTRATOR_HOST,
        port=Config.ORCHESTRATOR_PORT,
        ssl_keyfile=Config.SSL_KEY_PATH if not Config.DEVELOPMENT_MODE else None,
        ssl_certfile=Config.SSL_CERT_PATH if not Config.DEVELOPMENT_MODE else None,
        log_level=log_level_name
    )