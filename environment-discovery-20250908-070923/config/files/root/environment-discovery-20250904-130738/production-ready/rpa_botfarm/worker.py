"""
RPA Worker Service
-----------------
Worker service for executing RPA automation jobs.
Updated to use circuit_number for uniformity across all FNO providers.
"""
import sqlite3
from datetime import datetime, timezone, UTC
import base64
import logging
import json
import importlib
import os
import platform
import traceback
import time
from pathlib import Path
from ipaddress import ip_address, ip_network
from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import requests
from enum import Enum
from typing import Optional, Dict, Any, List
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_log,
    after_log,
    RetryError
)
from contextlib import contextmanager, asynccontextmanager

# Import shared configuration
from config import Config
from apscheduler.schedulers.background import BackgroundScheduler
from health_reporter import HealthReporter

worker_scheduler = BackgroundScheduler()

def send_worker_health_report():
    """Send health report to OGGIES_LOG via ORDS."""
    if not Config.HEALTH_REPORT_ENABLED:
        return
    
    try:
        reporter = HealthReporter(
            endpoint=Config.HEALTH_REPORT_ENDPOINT,
            server_type="Worker",
            db_path=Config.DB_PATH
        )
        
        if reporter.send():
            logger.info("Health report sent successfully")
    except Exception as e:
        logger.error(f"Error sending health report: {str(e)}")

# Start scheduler
if Config.HEALTH_REPORT_ENABLED:
    worker_scheduler.add_job(
        send_worker_health_report,
        'interval',
        seconds=Config.HEALTH_REPORT_INTERVAL,
        id='worker_health_report'
    )
    worker_scheduler.start()

# Make sure directories exist
Config.setup_directories()

# Configure logging
logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Global in-memory store for job status
class SQLiteJobStatusStore:
    def __init__(self, db_path=None):
        """
        Initialize SQLite job status store
        
        Args:
            db_path: Path to SQLite database. Defaults to a file in the worker's data directory.
        """
        if db_path is None:
            # Create a data directory in the worker's path if it doesn't exist
            data_dir = Path(__file__).parent / "worker_data"
            data_dir.mkdir(exist_ok=True)
            db_path = data_dir / "job_status.sqlite"
        
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Create job status table if it doesn't exist"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS job_status (
                    job_id INTEGER PRIMARY KEY,
                    status TEXT,
                    result TEXT,
                    start_time TEXT,
                    end_time TEXT
                )
            ''')

    def store_job_status(self, job_id, status, result=None, start_time=None, end_time=None):
        """
        Store or update job status in database
        
        Args:
            job_id: Unique job identifier
            status: Current job status
            result: Optional job result
            start_time: Optional job start time
            end_time: Optional job end time
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO job_status 
                (job_id, status, result, start_time, end_time) 
                VALUES (?, ?, ?, ?, ?)
            ''', (
                job_id, 
                status, 
                json.dumps(result) if result else None,
                start_time or datetime.now(timezone.utc).isoformat(),
                end_time
            ))

    def get_job_status(self, job_id):
        """
        Retrieve job status from database
        
        Args:
            job_id: Unique job identifier
        
        Returns:
            Dict containing job status information or None
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT * FROM job_status WHERE job_id = ?', 
                (job_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return {
                    "job_id": row[0],
                    "status": row[1],
                    "result": json.loads(row[2]) if row[2] else None,
                    "start_time": row[3],
                    "end_time": row[4]
                }
            return None

job_status_store = SQLiteJobStatusStore()

# Global job counter and statistics
ACTIVE_JOBS = 0
TOTAL_JOBS = 0
SUCCESSFUL_JOBS = 0
FAILED_JOBS = 0
START_TIME = datetime.now(UTC)

# Define models with validation
class JobStatus(str, Enum):
    """Job status states"""
    STARTED = "started"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    ERROR = "error"
    DONE = "done"

class ServiceProvider(str, Enum):
    """Fixed Network Operators (FNO) service providers"""
    MFN = "mfn"
    # Add other FNO providers as needed

class ActionType(str, Enum):
    """Available automation actions"""
    CANCELLATION = "cancellation"
    VALIDATION = "validation"
    # Add other actions as needed

class JobRequest(BaseModel):
    """Job request model for worker API"""
    job_id: int = Field(..., ge=1)
    provider: str
    action: str
    parameters: Dict[str, Any]
    
    @field_validator('provider')
    @classmethod
    def provider_must_be_valid(cls, v):
        valid_providers = ["mfn", "osn", "octotel", "evotel"]  # Zoom still needed
        if v.lower() not in [p.lower() for p in valid_providers]:
            raise ValueError(f"Provider must be one of {valid_providers}")
        return v.lower()
    

    @field_validator('action')
    @classmethod
    def action_must_be_valid(cls, v, info):
        values = info.data
        provider = values.get('provider')
        if provider == "octotel":  # Add Octotel validation
            valid_actions = ["validation", "cancellation"]
            if v.lower() not in [a.lower() for a in valid_actions]:
                raise ValueError(f"For provider 'octotel', action must be one of {valid_actions}")
        elif provider == "mfn":
            valid_actions = ["validation", "cancellation"]  # Extend as needed
            if v.lower() not in [a.lower() for a in valid_actions]:
                raise ValueError(f"For provider 'mfn', action must be one of {valid_actions}")
        elif provider == "osn":
            valid_actions = ["validation", "cancellation"]  # OSN actions
            if v.lower() not in [a.lower() for a in valid_actions]:
                raise ValueError(f"For provider 'osn', action must be one of {valid_actions}")
        elif provider == "evotel":
            valid_actions= ["validation", "cancellation"]
            if v.lower() not in [a.lower() for a in valid_actions]:
                raise ValueError(f"For provider 'evotel', action must be one of {valid_actions}")    
        return v.lower()

class JobResult(BaseModel):
    """Job result model"""
    status: str
    job_id: int
    result: Dict[str, Any]

# Custom exceptions
class AutomationError(Exception):
    """Base exception for automation errors"""
    pass

class ModuleLoadError(AutomationError):
    """Raised when an automation module fails to load"""
    pass

class ExecutionError(AutomationError):
    """Raised when module execution fails"""
    pass

class ValidationError(AutomationError):
    """Raised when validation of input parameters fails"""
    pass

# Setup lifespan context for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI application"""
    # Startup events
    # Ensure directories exist
    Config.setup_directories()
    
    # Log worker startup information
    logger.info(f"Worker started on {platform.node()} ({platform.system()})")
    logger.info(f"Python version: {platform.python_version()}")
    logger.info(f"Selenium available: {is_selenium_available()}")
    logger.info(f"Screenshot directory: {Config.SCREENSHOT_DIR}")
    
    # Discover available providers and actions
    automation_info = get_provider_actions()
    logger.info(f"Available providers: {', '.join(automation_info['providers'])}")
    for provider, actions in automation_info['actions'].items():
        logger.info(f"Provider {provider} actions: {', '.join(actions)}")
    
    yield
    
    # Shutdown events
    logger.info("Worker service shutting down")

# Initialize FastAPI app with lifespan context
app = FastAPI(
    title="RPA Worker Service",
    description="Worker service for executing RPA automation jobs",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware for IP validation
@app.middleware("http")
async def validate_ip_addresses(request: Request, call_next):
    """Validate client IP addresses against the authorized list."""
    client_ip = request.client.host
    
    # Skip IP validation for local testing
    if client_ip in ["127.0.0.1", "::1", "localhost"]:
        return await call_next(request)
        
    # Check if client IP is in authorized list
    authorized = False
    for allowed_ip in Config.AUTHORIZED_WORKER_IPS:
        # Support for IP networks (CIDR notation)
        if "/" in allowed_ip:
            try:
                if ip_address(client_ip) in ip_network(allowed_ip):
                    authorized = True
                    break
            except ValueError:
                continue
        # Direct IP comparison
        elif client_ip == allowed_ip:
            authorized = True
            break
            
    if not authorized:
        logger.warning(f"Unauthorized access attempt from IP: {client_ip}")
        return Response(
            content=json.dumps({"detail": "Unauthorized IP address"}),
            status_code=403,
            media_type="application/json"
        )
        
    return await call_next(request)

# Context manager for job stats tracking
@contextmanager
def job_stats_tracking():
    """Track job execution statistics."""
    global ACTIVE_JOBS, TOTAL_JOBS
    
    # Start tracking
    ACTIVE_JOBS += 1
    TOTAL_JOBS += 1
    
    try:
        yield
    finally:
        # End tracking
        ACTIVE_JOBS = max(0, ACTIVE_JOBS - 1)

# Helper functions
def is_selenium_available():
    """Check if Selenium is available."""
    try:
        import selenium
        return True
    except ImportError:
        return False

def get_provider_actions():
    """Discover available automation modules."""
    try:
        import pkgutil
        import automations
        
        providers = set()
        actions = {}
        
        # Find all provider modules
        for _, provider_name, is_pkg in pkgutil.iter_modules(automations.__path__):
            if is_pkg:
                providers.add(provider_name)
                provider_actions = []
                
                try:
                    provider_module = importlib.import_module(f"automations.{provider_name}")
                    
                    # Find all action modules for this provider
                    for _, action_name, _ in pkgutil.iter_modules(provider_module.__path__):
                        if not action_name.startswith("__"):
                            provider_actions.append(action_name)
                except (ImportError, AttributeError) as e:
                    logger.warning(f"Error loading provider {provider_name}: {str(e)}")
                
                if provider_actions:
                    actions[provider_name] = provider_actions
                    
        return {"providers": list(providers), "actions": actions}
                    
    except (ImportError, AttributeError) as e:
        logger.warning(f"Error discovering automation modules: {str(e)}")
        # Fallback to default capabilities if module discovery fails
        return {
            "providers": ["mfn"],
            "actions": {"mfn": ["validation", "cancellation"]}
        }

@retry(
    stop=stop_after_attempt(Config.MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=Config.RETRY_DELAY//3, max=Config.RETRY_DELAY),
    retry=retry_if_exception_type(ImportError),
    before=before_log(logger, logging.INFO),
    after=before_log(logger, logging.INFO)
)
def load_automation_module(provider: str, action: str):
    """Dynamically load the appropriate automation module for the provider with retry"""
    try:
        module_path = f"automations.{provider}.{action}"
        module = importlib.import_module(module_path)
        return module
    except ImportError as e:
        error_msg = f"Failed to load automation module: {module_path}"
        logger.error(f"{error_msg}: {str(e)}")
        raise ModuleLoadError(error_msg) from e

@retry(
    stop=stop_after_attempt(Config.MAX_RETRY_ATTEMPTS),
    wait=wait_exponential(multiplier=1, min=Config.RETRY_DELAY//3, max=Config.RETRY_DELAY),
    retry=retry_if_exception_type(Exception),
    before=before_log(logger, logging.INFO),
    after=before_log(logger, logging.INFO)
)
def execute_with_retry(module, parameters):
    """Execute module with retry capability"""
    try:
        # Execute the module
        return module.execute(parameters)
    except Exception as e:
        logger.error(f"Module execution failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise ExecutionError(f"Module execution failed: {str(e)}") from e

def validate_job_parameters(provider: str, action: str, parameters: Dict[str, Any]):
    """Validate job parameters based on provider and action - Updated to use circuit_number for uniformity"""
    required_params = []
    
    # Define required parameters based on provider and action
    # ALL providers now use circuit_number for uniformity
    if provider == "mfn":
        if action == "validation":
            required_params = ["circuit_number"]
        elif action == "cancellation":
            required_params = ["circuit_number"]
    
    elif provider == "osn":
        if action == "validation":
            required_params = ["circuit_number"]
        elif action == "cancellation":
            required_params = ["circuit_number", "solution_id"]
    
    elif provider == "octotel":
        if action == "validation":
            required_params = ["circuit_number"]
        elif action == "cancellation":
            required_params = ["circuit_number", "solution_id"]

    elif provider == "evotel":  # Updated Evotel parameter validation
        if action == "validation":
            required_params = ["circuit_number"]  # Changed from serial_number to circuit_number
        elif action == "cancellation":
            required_params = ["circuit_number"]  # Changed from serial_number to circuit_number

    # Check for required parameters
    missing_params = [param for param in required_params if param not in parameters]
    if missing_params:
        raise ValidationError(f"Missing required parameters: {', '.join(missing_params)}")
    
    # BACKWARD COMPATIBILITY: Handle legacy serial_number parameter for Evotel
    if provider == "evotel" and "serial_number" in parameters and "circuit_number" not in parameters:
        logger.info("Converting legacy serial_number parameter to circuit_number for Evotel")
        parameters["circuit_number"] = parameters["serial_number"]
        # Don't remove serial_number yet, let the module handle both for now
        logger.info(f"Mapped serial_number '{parameters['serial_number']}' to circuit_number for uniformity")
    
    # Fix for parameter mapping
    # Map external_job_id to job_id if it exists and job_id doesn't
    if "external_job_id" in parameters and "job_id" not in parameters:
        parameters["job_id"] = parameters["external_job_id"]
        logger.info(f"Mapped external_job_id '{parameters['external_job_id']}' to job_id")
    
    # Create a default job_id if none exists
    if "job_id" not in parameters and "order_id" not in parameters:
        import time
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        parameters["job_id"] = f"AUTO_{int(time.time())}_{unique_id}"
        logger.info(f"Created auto job_id: {parameters['job_id']}")
    
    return True

# API Endpoints
@app.get("/status")
async def get_status():
    """Report worker status and capabilities."""
    uptime = str(datetime.now(UTC) - START_TIME)
    
    # Get provider and action information
    automation_info = get_provider_actions()
    
    return {
        "status": "online",
        "version": "1.0.0",
        "uptime": uptime,
        "hostname": platform.node(),
        "system": platform.system(),
        "python_version": platform.python_version(),
        "selenium_available": is_selenium_available(),
        "providers": automation_info["providers"],
        "actions": automation_info["actions"],
        "job_stats": {
            "active": ACTIVE_JOBS,
            "total": TOTAL_JOBS,
            "successful": SUCCESSFUL_JOBS,
            "failed": FAILED_JOBS
        },
        "capacity": {
            "max_concurrent": Config.MAX_WORKERS,
            "current_load": ACTIVE_JOBS
        }
    }


@app.post("/execute", response_model=JobResult)
def execute_job(job: JobRequest):
    """Main endpoint to execute automation jobs for FNO providers with improved error handling"""
    global SUCCESSFUL_JOBS, FAILED_JOBS
    
    job_id = job.job_id
    start_time = datetime.now(timezone.utc).isoformat()
    logger.info(f"Received job request: {job_id} - {job.provider}/{job.action}")
    
    # Store initial job status
    job_status_store.store_job_status(
        job_id, 
        "in_progress", 
        start_time=start_time
    )
    
    with job_stats_tracking():
        try:
            # Validate job parameters
            try:
                validate_job_parameters(job.provider, job.action, job.parameters)
            except ValidationError as e:
                logger.error(f"Validation error for job {job_id}: {str(e)}")
                
                end_time = datetime.now(timezone.utc).isoformat()
                job_status_store.store_job_status(
                    job_id, 
                    "error", 
                    result={"error": str(e), "error_type": "ValidationError"},
                    start_time=start_time,
                    end_time=end_time
                )
                
                FAILED_JOBS += 1
                
                return {
                    "status": "error",
                    "job_id": job_id,
                    "result": {
                        "error": str(e),
                        "error_type": "ValidationError",
                        "start_time": start_time,
                        "end_time": end_time
                    }
                }
                                    
            # Load automation module
            try:
                module = load_automation_module(job.provider, job.action)
            except ModuleLoadError as e:
                logger.error(f"Module load error for job {job_id}: {str(e)}")
                
                end_time = datetime.now(timezone.utc).isoformat()
                job_status_store.store_job_status(
                    job_id, 
                    "error", 
                    result={"error": str(e), "error_type": "ModuleLoadError"},
                    start_time=start_time,
                    end_time=end_time
                )
                
                FAILED_JOBS += 1
                
                return {
                    "status": "error",
                    "job_id": job_id,
                    "result": {
                        "error": str(e),
                        "error_type": "ModuleLoadError",
                        "start_time": start_time,
                        "end_time": end_time
                    }
                }

            job_params = job.parameters.copy()
            # Execute the module with retry
            try:
                result = execute_with_retry(module, job_params)
                
                # CRITICAL: Ensure result is always a dictionary
                if result is None:
                    logger.warning(f"Job {job_id}: Module returned None, creating default result")
                    result = {
                        "status": "completed",
                        "message": "Job completed but returned no result data",
                        "details": {}
                    }
                elif not isinstance(result, dict):
                    logger.warning(f"Job {job_id}: Module returned non-dict result: {type(result)}")
                    result = {
                        "status": "completed", 
                        "message": "Job completed with non-standard result format",
                        "details": {"original_result": str(result)}
                    }
                    
            except ExecutionError as e:
                logger.error(f"Execution error for job {job_id}: {str(e)}")
                
                end_time = datetime.now(timezone.utc).isoformat()
                job_status_store.store_job_status(
                    job_id, 
                    "error", 
                    result={"error": str(e), "error_type": "ExecutionError"},
                    start_time=start_time,
                    end_time=end_time
                )
                
                FAILED_JOBS += 1
                
                return {
                    "status": "error",
                    "job_id": job_id,
                    "result": {
                        "error": str(e),
                        "error_type": "ExecutionError",
                        "start_time": start_time,
                        "end_time": end_time
                    }
                }

            # Add job_id to the result if not present
            if isinstance(result, dict) and 'job_id' not in result:
                result['job_id'] = job.job_id

            # Ensure screenshot_data always exists in results
            if isinstance(result, dict) and 'screenshot_data' not in result:
                result['screenshot_data'] = []
                
            # Add timestamps to the result
            if isinstance(result, dict):
                result['start_time'] = start_time
                result['end_time'] = datetime.now(timezone.utc).isoformat()
                
            # Check for failure status
            if isinstance(result, dict) and result.get("status") == "failure":
                logger.error(f"Job {job_id} failed with internal status 'failure'")
                FAILED_JOBS += 1
                
                # Update job status
                job_status_store.store_job_status(
                    job_id, 
                    "error", 
                    result=result, 
                    start_time=start_time,
                    end_time=result.get('end_time')
                )
                
                return {
                    "status": "error",  # Propagate error status to orchestrator
                    "job_id": job_id,
                    "result": result
                }
            
            # Job was successful
            logger.info(f"Job {job_id} completed successfully")
            SUCCESSFUL_JOBS += 1
            
            end_time = datetime.now(timezone.utc).isoformat()
            job_status_store.store_job_status(
                job_id, 
                "success", 
                result=result, 
                start_time=start_time,
                end_time=end_time
            )
            
            # FINAL VALIDATION: Ensure result is always a dict for response
            if not isinstance(result, dict):
                logger.warning(f"Job {job_id}: Converting non-dict result to dict for response")
                result = {
                    "status": "completed",
                    "message": "Job completed successfully",
                    "details": {"data": result} if result is not None else {}
                }
            
            return {
                "status": "success",
                "job_id": job_id,
                "result": result
            }
        
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            logger.error(f"Unexpected error executing job {job_id}: {error_type} - {error_msg}")
            logger.error(traceback.format_exc())
            
            end_time = datetime.now(timezone.utc).isoformat()
            # Store error status
            job_status_store.store_job_status(
                job_id, 
                "error", 
                result={"error": error_msg, "error_type": error_type, "traceback": traceback.format_exc()},
                start_time=start_time,
                end_time=end_time
            )
            
            FAILED_JOBS += 1
            
            return {
                "status": "error",
                "job_id": job_id,
                "result": {
                    "error": error_msg,
                    "error_type": error_type,
                    "start_time": start_time,
                    "end_time": end_time
                }
            }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_jobs": ACTIVE_JOBS
    }

@app.get("/status/{job_id}")
def get_job_status(job_id: int):
    """
    Get the status of a specific job.
    
    Args:
        job_id: The ID of the job to check
        
    Returns:
        dict: Job status information
    """
    logger.info(f"Received status check for job {job_id}")
    
    # Use SQLite-backed job status store
    status_info = job_status_store.get_job_status(job_id)
    
    if status_info:
        logger.info(f"Found status for job {job_id}: {status_info['status']}")
        # Ensure consistent status format for orchestrator
        # Map internal statuses to orchestrator-expected statuses
        status_mapping = {
            "in_progress": "running",
            "success": "completed",
            "error": "failed"
        }
        
        reported_status = status_info.get('status')
        if reported_status in status_mapping:
            status_info['status'] = status_mapping[reported_status]
            
        # Ensure job_id is included and is an integer
        status_info['job_id'] = int(job_id)
        
        return status_info
    else:
        logger.warning(f"No status information found for job {job_id}")
        return {
            "job_id": job_id,
            "status": "not_found",
            "message": f"No status information for job {job_id}"
        }

# Main entry point
if __name__ == "__main__":
    import uvicorn
    
    # Convert Python logging level to string name and lowercase it for uvicorn
    log_level_name = logging.getLevelName(Config.LOG_LEVEL).lower()
    
    uvicorn.run(
        app,
        host=Config.WORKER_HOST,
        port=Config.WORKER_PORT,
        log_level=log_level_name
    )