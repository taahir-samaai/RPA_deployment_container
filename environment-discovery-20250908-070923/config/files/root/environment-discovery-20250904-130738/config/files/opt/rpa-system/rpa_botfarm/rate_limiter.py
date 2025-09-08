# rate_limiter.py
import sqlite3
from datetime import datetime, timedelta
import threading
from fastapi import Request
from fastapi.responses import JSONResponse

class SQLiteRateLimiter:
    def __init__(self, db_path: str = "rate_limits.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        """Initialize rate limiting table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY,
                    count INTEGER DEFAULT 0,
                    window_start TIMESTAMP,
                    last_request TIMESTAMP
                )
            """)
            
            # Create index for faster cleanup
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_window_start 
                ON rate_limits(window_start)
            """)
            
            # Clean up old entries
            self._cleanup_old_entries()
    
    def _cleanup_old_entries(self):
        """Remove entries older than 1 hour"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                DELETE FROM rate_limits 
                WHERE window_start < datetime('now', '-1 hour')
            """)
    
    def is_allowed(self, key: str, limit: int, window_seconds: int = 3600) -> bool:
        """Check if request is allowed within rate limit"""
        with self.lock:
            now = datetime.now()
            window_start = now - timedelta(seconds=window_seconds)
            
            with sqlite3.connect(self.db_path) as conn:
                # Get current count
                result = conn.execute(
                    "SELECT count, window_start FROM rate_limits WHERE key = ?",
                    (key,)
                ).fetchone()
                
                if not result:
                    # First request
                    conn.execute(
                        """INSERT INTO rate_limits 
                        (key, count, window_start, last_request) 
                        VALUES (?, 1, ?, ?)""",
                        (key, now, now)
                    )
                    return True
                
                count, stored_window_start = result
                stored_window_start = datetime.fromisoformat(stored_window_start)
                
                # Check if window expired
                if stored_window_start < window_start:
                    # Reset window
                    conn.execute(
                        """UPDATE rate_limits 
                        SET count = 1, window_start = ?, last_request = ? 
                        WHERE key = ?""",
                        (now, now, key)
                    )
                    return True
                
                # Check limit
                if count >= limit:
                    return False
                
                # Increment counter
                conn.execute(
                    """UPDATE rate_limits 
                    SET count = count + 1, last_request = ? 
                    WHERE key = ?""",
                    (now, key)
                )
                return True
    
    def get_remaining(self, key: str, limit: int) -> int:
        """Get remaining requests in current window"""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "SELECT count FROM rate_limits WHERE key = ?",
                (key,)
            ).fetchone()
            
            if not result:
                return limit
            
            return max(0, limit - result[0])

# Initialize rate limiter
rate_limiter = SQLiteRateLimiter()

# Rate limiting middleware
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting to requests"""
    
    # Get identifier
    client_ip = request.client.host
    api_key = request.headers.get("X-API-Key", "")
    
    # Use API key if available, otherwise IP
    rate_key = f"api:{api_key}" if api_key else f"ip:{client_ip}"
    
    # Define limits per endpoint
    endpoint_limits = {
        "/jobs": 100,        # 100 jobs per hour
        "/health": 1000,     # 1000 health checks per hour
        "/token": 50,        # 50 token requests per hour
        "/execute": 200,     # 200 executions per hour
    }
    
    # Get limit for this endpoint
    path = request.url.path
    limit = endpoint_limits.get(path, 200)  # Default 200/hour
    
    # Check rate limit
    if not rate_limiter.is_allowed(rate_key, limit):
        remaining = rate_limiter.get_remaining(rate_key, limit)
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "limit": limit,
                "remaining": remaining,
                "reset_in_seconds": 3600
            },
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(3600),
                "Retry-After": "3600"
            }
        )
    
    # Add rate limit headers to response
    response = await call_next(request)
    remaining = rate_limiter.get_remaining(rate_key, limit)
    
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    
    return response