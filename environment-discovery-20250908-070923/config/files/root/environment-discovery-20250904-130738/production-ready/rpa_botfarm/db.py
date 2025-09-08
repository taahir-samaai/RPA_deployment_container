"""
RPA Orchestration System - Database Utilities
--------------------------------------------
Database connection and utility functions for the RPA orchestration system.
Uses SQLAlchemy for improved connection handling with SQLite backend.
"""

import os
import json
import datetime
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, scoped_session
from sqlalchemy.pool import QueuePool
from sqlalchemy.engine import Engine
from sqlalchemy import event
from sqlalchemy.sql import func
import sqlalchemy.types as types
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import LargeBinary
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON
from sqlalchemy import text

from config import Config

logger = logging.getLogger(__name__)

# Create a custom JSON data type for SQLAlchemy
class JSONType(types.TypeDecorator):
    impl = Text

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return {}
        return None

# SQLite foreign key support
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()

# Create base model class
Base = declarative_base()

# Define models
class User(Base):
    __tablename__ = 'api_users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String(100), nullable=False)
    disabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    last_login = Column(DateTime, nullable=True)

class JobQueue(Base):
    __tablename__ = 'job_queue'
    
    id = Column(Integer, primary_key=True)
    external_job_id = Column(String(100), nullable=True, index=True)  # Renamed from job_id to external_job_id
    provider = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    parameters = Column(JSONType, nullable=False)
    priority = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    scheduled_for = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    result = Column(JSONType, nullable=True)
    evidence = Column(JSONType, nullable=True)
    assigned_worker = Column(String(100), nullable=True)
    lock_id = Column(String(36), nullable=True)
    locked_at = Column(DateTime, nullable=True)
    
    # Relationships
    history = relationship("JobHistory", back_populates="job", cascade="all, delete-orphan")
    screenshots = relationship("Screenshot", back_populates="job", cascade="all, delete-orphan")




class Screenshot(Base):
    __tablename__ = 'job_screenshots'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('job_queue.id', ondelete='CASCADE'), nullable=False)
    name = Column(String(100), nullable=False)
    timestamp = Column(DateTime, default=func.now())
    mime_type = Column(String(50), default="image/png")
    description = Column(String(255), nullable=True)
    image_data = Column(Text, nullable=False)  # Base64 encoded image
    
    # Relationships
    job = relationship("JobQueue", back_populates="screenshots")

class JobHistory(Base):
    __tablename__ = 'job_history'
    
    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey('job_queue.id'), nullable=False)
    status = Column(String(20), nullable=False)
    timestamp = Column(DateTime, default=func.now())
    details = Column(Text, nullable=True)
    
    # Relationships
    job = relationship("JobQueue", back_populates="history")

class SystemMetrics(Base):
    __tablename__ = 'system_metrics'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now())
    queued_jobs = Column(Integer, default=0)
    running_jobs = Column(Integer, default=0)
    completed_jobs = Column(Integer, default=0)
    failed_jobs = Column(Integer, default=0)
    worker_status = Column(JSONType, nullable=True)

# Engine and session setup
def create_db_engine():
    """Create SQLAlchemy engine for database connection."""
    # Ensure directory exists
    Path(Config.DB_DIR).mkdir(parents=True, exist_ok=True)
    
    # Create SQLite URL
    db_url = f"sqlite:///{Config.DB_PATH}"
    
    # Create engine with connection pooling and improved settings
    engine = create_engine(
        db_url,
        poolclass=QueuePool,
        pool_size=10,          # Increased from 5
        max_overflow=20,       # Increased from 10
        pool_timeout=30,
        pool_recycle=1800,     # Reduced from 3600 (30 mins instead of 60)
        pool_pre_ping=True,    # Added to test connections before use
        connect_args={
            "check_same_thread": False,  # Needed for SQLite
            "timeout": 30  # SQLite timeout in seconds
        }
    )
    
    return engine

# Create engine and session factory
engine = create_db_engine()
session_factory = sessionmaker(bind=engine)
SessionLocal = scoped_session(session_factory)

@contextmanager
def db_session():
    """Context manager for database sessions with improved error handling."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Database error: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Unexpected error in database session: {str(e)}")
        logger.error(traceback.format_exc())
        raise
    finally:
        session.close()

def init_db():
    """
    Initialize the database schema if it doesn't exist yet.
    
    Returns:
        bool: True if initialization was successful, False otherwise
    """
    try:
        # Create tables if they don't exist
        Base.metadata.create_all(engine)
        logger.info("Database tables created or verified")
        return True
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")
        return False

def recover_database():
    """Try to recover database from WAL files if present."""
    try:
        import sqlite3
        # Connect directly to the database file
        conn = sqlite3.connect(Config.DB_PATH)
        # Force a checkpoint to merge WAL content into the main database file
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
        logger.info("Database recovery attempted")
        return True
    except Exception as e:
        logger.error(f"Database recovery failed: {str(e)}")
        return False

def to_dict(model) -> Dict:
    """Convert SQLAlchemy model to dictionary."""
    result = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        # Handle datetime objects
        if isinstance(value, datetime.datetime):
            result[column.name] = value.isoformat()
        else:
            result[column.name] = value
    return result

def get_pending_jobs(limit: int = 10) -> List[Dict]:
    """Get pending jobs ordered by priority."""
    with db_session() as session:
        now = datetime.datetime.utcnow()
        jobs = (
            session.query(JobQueue)
            .filter(
                (
                    (JobQueue.status == "pending") |
                    ((JobQueue.status == "retry_pending") & (JobQueue.scheduled_for <= now))
                ) &
                (JobQueue.lock_id.is_(None))
            )
            .order_by(JobQueue.priority.desc(), JobQueue.created_at.asc())
            .limit(limit)
            .all()
        )
        return [to_dict(job) for job in jobs]

def create_job(
    provider: str, 
    action: str, 
    parameters: Dict[str, Any], 
    external_job_id: Optional[str] = None,  # Keep this parameter name
    priority: int = 0, 
    retry_count: int = 0, 
    max_retries: int = 3
) -> Dict:
    """Create a new job in the database."""
    with db_session() as session:
        job = JobQueue(
            provider=provider,
            action=action,
            parameters=parameters,
            external_job_id=external_job_id,  # Map to external_job_id field
            priority=priority,
            retry_count=retry_count,
            max_retries=max_retries,
            status="pending"  # Ensure status is explicitly set
        )
        session.add(job)
        session.flush()  # Flush to get the job ID
        
        # Add job history
        history = JobHistory(
            job_id=job.id,  # Use internal job ID for the relationship
            status="created",
            details=f"Job created with external ID: {external_job_id}" if external_job_id else "Job created"
        )
        session.add(history)
        
        # Convert to dictionary
        job_dict = to_dict(job)
        
        # Ensure status is set
        if 'status' not in job_dict or job_dict['status'] is None:
            job_dict['status'] = 'pending'
            
        return job_dict

def update_job_status(
    job_id: int, 
    status: str, 
    result: Optional[Dict] = None, 
    evidence: Optional[List[str]] = None, 
    assigned_worker: Optional[str] = None
) -> Optional[Dict]:
    """Update job status in the database."""
    with db_session() as session:
        job = session.query(JobQueue).filter(JobQueue.id == job_id).first()
        if not job:
            return None
        
        job.status = status
        
        if status == "started" or status == "running":
            job.started_at = datetime.datetime.utcnow()
        
        if status in ["completed", "failed", "error", "cancelled"]:
            job.completed_at = datetime.datetime.utcnow()
        
        # Handle screenshot data before assigning result
        screenshot_data = None
        if result is not None:
            # Extract and remove screenshot_data from result
            screenshot_data = result.pop('screenshot_data', None)
            job.result = result
        
        if evidence is not None:
            job.evidence = evidence
        
        if assigned_worker is not None:
            job.assigned_worker = assigned_worker
        
        # Add history entry
        details = f"Job status changed to {status}"
        if result:
            result_str = json.dumps(result)
            details += f" with result summary: {result_str[:100]}..." if len(result_str) > 100 else f" with result: {result_str}"
            
        history = JobHistory(
            job_id=job.id,
            status=status,
            details=details
        )
        session.add(history)
        
        # Process screenshot data if provided
        if screenshot_data:
            for screenshot_info in screenshot_data:
                # Skip if missing required fields
                if 'base64_data' not in screenshot_info or 'name' not in screenshot_info:
                    continue
                    
                screenshot = Screenshot(
                    job_id=job_id,
                    name=screenshot_info["name"],
                    mime_type=screenshot_info.get("mime_type", "image/png"),
                    description=screenshot_info.get("description", None),
                    image_data=screenshot_info["base64_data"]
                )
                session.add(screenshot)
            
            logger.info(f"Saved {len(screenshot_data)} screenshots for job {job_id}")
        
        return to_dict(job)

def update_job_retry_count(job_id: int, retry_count: int) -> bool:
    """Update job retry count."""
    with db_session() as session:
        job = session.query(JobQueue).filter(JobQueue.id == job_id).first()
        if not job:
            return False
        
        job.retry_count = retry_count
        return True

def acquire_job_lock(job_id: int, lock_id: str) -> bool:
    """
    Acquire a lock on a job for exclusive processing.
    
    Args:
        job_id: ID of the job to lock
        lock_id: Unique identifier for the lock
        
    Returns:
        bool: True if lock acquired, False otherwise
    """
    with db_session() as session:
        try:
            # Try to update the job with our lock
            result = (
                session.query(JobQueue)
                .filter(
                    JobQueue.id == job_id,
                    JobQueue.lock_id.is_(None),
                    JobQueue.status.in_(["pending", "retry_pending"])
                )
                .update({
                    "lock_id": lock_id,
                    "locked_at": datetime.datetime.utcnow()
                })
            )
            
            # Return True if a row was updated (lock acquired)
            return result > 0
        except SQLAlchemyError as e:
            logger.error(f"Error acquiring job lock: {str(e)}")
            return False

def release_job_lock(job_id: int, lock_id: str, status: str = "pending") -> bool:
    """
    Release a lock on a job.
    
    Args:
        job_id: ID of the job to unlock
        lock_id: Lock ID to verify ownership
        status: New status for the job
        
    Returns:
        bool: True if lock released, False otherwise
    """
    with db_session() as session:
        try:
            # Only release if we own the lock
            result = (
                session.query(JobQueue)
                .filter(
                    JobQueue.id == job_id,
                    JobQueue.lock_id == lock_id
                )
                .update({
                    "lock_id": None,
                    "locked_at": None,
                    "status": status
                })
            )
            
            # Return True if a row was updated (lock released)
            return result > 0
        except SQLAlchemyError as e:
            logger.error(f"Error releasing job lock: {str(e)}")
            return False

def recover_stale_locks(max_lock_age_minutes: int = 30) -> int:
    """
    Recover jobs with stale locks.
    
    Args:
        max_lock_age_minutes: Maximum age of a lock in minutes
        
    Returns:
        int: Number of recovered locks
    """
    with db_session() as session:
        try:
            cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(minutes=max_lock_age_minutes)
            
            # Find jobs with stale locks
            stale_jobs = (
                session.query(JobQueue)
                .filter(
                    JobQueue.lock_id.isnot(None),
                    JobQueue.locked_at < cutoff_time,
                    # Only recover jobs that are in a state that makes sense to recover
                    JobQueue.status.in_(["dispatching", "running", "retry_pending"])
                )
                .all()
            )
            
            count = 0
            for job in stale_jobs:
                # Add history entry
                history = JobHistory(
                    job_id=job.id,
                    status="recovered",
                    details=f"Recovered stale lock from {job.locked_at.isoformat()}, previous status: {job.status}"
                )
                session.add(history)
                
                # Reset the job
                job.lock_id = None
                job.locked_at = None
                
                # Set status based on previous status
                if job.status == "running" and job.retry_count < job.max_retries:
                    job.status = "retry_pending"
                    job.retry_count += 1
                else:
                    job.status = "pending"
                    
                count += 1
                
                logger.info(f"Recovered stale lock for job {job.id}")
            
            return count
        except SQLAlchemyError as e:
            logger.error(f"Error recovering stale locks: {str(e)}")
            return 0

def collect_system_metrics(metrics_data: Dict[str, Any]) -> bool:
    """Store system metrics in the database."""
    with db_session() as session:
        try:
            metrics = SystemMetrics(
                queued_jobs=metrics_data.get("queued_jobs", 0),
                running_jobs=metrics_data.get("running_jobs", 0),
                completed_jobs=metrics_data.get("completed_jobs", 0),
                failed_jobs=metrics_data.get("failed_jobs", 0),
                worker_status=metrics_data.get("workers", {})
            )
            session.add(metrics)
            return True
        except SQLAlchemyError as e:
            logger.error(f"Error collecting metrics: {str(e)}")
            return False

def get_user_by_username(username: str) -> Optional[Dict]:
    """Get a user by username."""
    with db_session() as session:
        user = session.query(User).filter(User.username == username).first()
        if user:
            return to_dict(user)
        return None

def create_user(username: str, hashed_password: str, disabled: bool = False) -> Optional[Dict]:
    """Create a new user."""
    with db_session() as session:
        try:
            user = User(
                username=username,
                hashed_password=hashed_password,
                disabled=disabled
            )
            session.add(user)
            return to_dict(user)
        except SQLAlchemyError as e:
            logger.error(f"Error creating user: {str(e)}")
            return None

def update_user_last_login(username: str) -> bool:
    """Update user's last login timestamp."""
    with db_session() as session:
        try:
            user = session.query(User).filter(User.username == username).first()
            if user:
                user.last_login = datetime.datetime.utcnow()
                return True
            return False
        except SQLAlchemyError as e:
            logger.error(f"Error updating user last login: {str(e)}")
            return False

def get_job(job_id: int) -> Optional[Dict]:
    """Get job details from the database."""
    with db_session() as session:
        job = session.query(JobQueue).filter(JobQueue.id == job_id).first()
        if job:
            job_dict = to_dict(job)
            # Ensure status is never None
            if 'status' not in job_dict or job_dict['status'] is None:
                job_dict['status'] = "pending"
            return job_dict
        return None

def get_job_history(job_id: int) -> List[Dict]:
    """Get job history."""
    try:
        with db_session() as session:
            # Check if job exists first
            job = session.query(JobQueue).filter(JobQueue.id == job_id).first()
            if not job:
                logger.warning(f"Job {job_id} not found in get_job_history")
                return []
            
            # Get history records
            history_records = (
                session.query(JobHistory)
                .filter(JobHistory.job_id == job_id)
                .order_by(JobHistory.timestamp)
                .all()
            )
            
            # Convert to dictionaries
            history = [to_dict(record) for record in history_records]
            
            # If no history found, return at least one entry
            if not history:
                logger.info(f"No history found for job {job_id}, creating default entry")
                # Create a default history entry
                default_history = {
                    "id": 0,
                    "job_id": job_id,
                    "status": job.status or "pending",
                    "timestamp": job.created_at.isoformat() if hasattr(job, 'created_at') and job.created_at else datetime.datetime.now().isoformat(),
                    "details": "Job created"
                }
                return [default_history]
            
            return history
    except Exception as e:
        logger.error(f"Error in get_job_history for job {job_id}: {str(e)}")
        # Return an empty list instead of None
        return []

def get_job_by_external_id(external_job_id: str) -> Optional[Dict]:
    """Get job details from the database by external ID."""
    with db_session() as session:
        job = session.query(JobQueue).filter(JobQueue.external_job_id == external_job_id).first()
        if job:
            job_dict = to_dict(job)
            # Ensure status is never None
            if 'status' not in job_dict or job_dict['status'] is None:
                job_dict['status'] = "pending"
            return job_dict
        return None

def get_recent_metrics(limit: int = 24) -> List[Dict]:
    """Get recent system metrics."""
    with db_session() as session:
        metrics = (
            session.query(SystemMetrics)
            .order_by(SystemMetrics.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [to_dict(metric) for metric in metrics]

def get_jobs_by_status(status: str, limit: int = 100, offset: int = 0) -> List[Dict]:
    """Get jobs by status with pagination."""
    with db_session() as session:
        jobs = (
            session.query(JobQueue)
            .filter(JobQueue.status == status)
            .order_by(JobQueue.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [to_dict(job) for job in jobs]

def get_jobs_count_by_status() -> Dict[str, int]:
    """Get count of jobs by status."""
    with db_session() as session:
        result = {}
        for status in ["pending", "running", "completed", "failed", "error", "cancelled"]:
            count = session.query(JobQueue).filter(JobQueue.status == status).count()
            result[status] = count
        return result

def save_screenshots_for_job(job_id: int, screenshot_data: List[Dict]) -> int:
    """
    Save multiple screenshots for a job in a single transaction.
    Checks for duplicates based on name and timestamp.
    
    Args:
        job_id: ID of the job
        screenshot_data: List of screenshot data dictionaries
            Each dict should contain: name, base64_data, and optionally mime_type and description
    
    Returns:
        int: Number of screenshots successfully saved
    """
    with db_session() as session:
        try:
            count = 0
            
            # Get existing screenshots for this job to avoid duplicates
            existing_screenshots = session.query(Screenshot).filter(Screenshot.job_id == job_id).all()
            existing_names = {s.name for s in existing_screenshots}
            
            for screenshot_info in screenshot_data:
                # Skip if missing required fields
                if 'base64_data' not in screenshot_info or 'name' not in screenshot_info:
                    logger.warning(f"Skipping screenshot with missing fields for job {job_id}")
                    continue
                
                # Skip duplicates based on name
                if screenshot_info["name"] in existing_names:
                    logger.debug(f"Skipping duplicate screenshot '{screenshot_info['name']}' for job {job_id}")
                    continue
                
                try:
                    # Create screenshot record
                    screenshot = Screenshot(
                        job_id=job_id,
                        name=screenshot_info["name"],
                        mime_type=screenshot_info.get("mime_type", "image/png"),
                        description=screenshot_info.get("description"),
                        image_data=screenshot_info["base64_data"]
                    )
                    
                    session.add(screenshot)
                    existing_names.add(screenshot_info["name"])  # Update tracked names
                    count += 1
                    
                except SQLAlchemyError as e:
                    logger.error(f"Error saving screenshot '{screenshot_info.get('name')}' for job {job_id}: {str(e)}")
                    continue
            
            return count
        except SQLAlchemyError as e:
            logger.error(f"Error saving screenshots: {str(e)}")
            return 0

def get_job_screenshots(job_id: int, include_data: bool = False) -> List[Dict]:
    """
    Get screenshots associated with a job.
    
    Args:
        job_id: ID of the job
        include_data: Whether to include the image data (can be large)
        
    Returns:
        List[Dict]: List of screenshot metadata
    """
    with db_session() as session:
        try:
            screenshots = session.query(Screenshot).filter(Screenshot.job_id == job_id).all()
            
            result = []
            for screenshot in screenshots:
                data = to_dict(screenshot)
                
                # Remove image_data if not requested to reduce payload size
                if not include_data:
                    data.pop('image_data', None)
                    
                result.append(data)
                
            return result
        except SQLAlchemyError as e:
            logger.error(f"Error retrieving screenshots: {str(e)}")
            return []