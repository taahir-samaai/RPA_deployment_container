# secure_errors.py
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
import logging
import traceback
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class SecurityEventLogger:
    """Log security-relevant events for monitoring"""
    
    def __init__(self, log_file: str = "security_events.log"):
        self.security_logger = logging.getLogger("security")
        handler = logging.FileHandler(log_file)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s|%(levelname)s|%(message)s"
            )
        )
        self.security_logger.addHandler(handler)
        self.security_logger.setLevel(logging.INFO)
    
    def log_event(self, event_type: str, details: dict):
        """Log security event with structured data"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event_type,
            **details
        }
        self.security_logger.info(log_entry)

# Initialize security logger
security_logger = SecurityEventLogger()

# Global exception handler
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions - no info disclosure"""
    
    # Generate correlation ID
    correlation_id = str(uuid.uuid4())
    
    # Log full error internally
    logger.error(f"Unhandled exception [{correlation_id}]")
    logger.error(f"Request: {request.method} {request.url.path}")
    logger.error(f"Client: {request.client.host}")
    logger.error(f"Exception: {type(exc).__name__}: {str(exc)}")
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    
    # Generic response to client
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "correlation_id": correlation_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# HTTP exception handler
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with security logging"""
    
    # Log security-relevant errors
    if exc.status_code in [401, 403, 429]:
        security_logger.log_event(
            event_type=f"HTTP_{exc.status_code}",
            details={
                "ip": request.client.host,
                "path": request.url.path,
                "method": request.method,
                "detail": exc.detail,
                "headers": dict(request.headers)
            }
        )
    
    # Return safe error response
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# Validation error handler
async def validation_error_handler(request: Request, exc: ValueError):
    """Handle validation errors without exposing internals"""
    
    correlation_id = str(uuid.uuid4())
    
    # Log detailed error
    logger.error(f"Validation error [{correlation_id}]: {str(exc)}")
    security_logger.log_event(
        event_type="VALIDATION_ERROR",
        details={
            "ip": request.client.host,
            "path": request.url.path,
            "correlation_id": correlation_id
        }
    )
    
    # Generic response
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Invalid request data",
            "correlation_id": correlation_id
        }
    )
