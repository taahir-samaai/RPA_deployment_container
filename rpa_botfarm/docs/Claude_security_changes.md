# Security Adjustments for RPA Automation System

## Phase 1: Immediate Security Fixes for Cancellation & Validation Scripts

### 1. Secure Credential Management
**Current Issue**: Hardcoded credentials in config files
**Solution**: Implement HashiCorp Vault integration

```python
# security/vault_client.py
import hvac
from typing import Dict, Optional
import logging

class VaultClient:
    def __init__(self, vault_url: str, vault_token: str):
        self.client = hvac.Client(url=vault_url, token=vault_token)
        self.logger = logging.getLogger(__name__)
    
    def get_bot_credentials(self, provider: str) -> Dict[str, str]:
        """Get provider-specific credentials from Vault"""
        try:
            secret_path = f"rpa/{provider.lower()}/credentials"
            response = self.client.secrets.kv.v2.read_secret_version(path=secret_path)
            return response['data']['data']
        except Exception as e:
            self.logger.error(f"Failed to retrieve credentials for {provider}: {e}")
            raise SecurityError(f"Credential retrieval failed for {provider}")

# Updated config.py
class SecureConfig:
    def __init__(self):
        self.vault_client = VaultClient(
            vault_url=os.getenv("VAULT_URL"),
            vault_token=os.getenv("VAULT_TOKEN")
        )
    
    def get_octotel_credentials(self) -> Dict[str, str]:
        return self.vault_client.get_bot_credentials("octotel")
    
    def get_osn_credentials(self) -> Dict[str, str]:
        return self.vault_client.get_bot_credentials("osn")
```

### 2. Enhanced Authentication & Authorization

```python
# security/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
import jwt
from typing import List

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://your-idp.com/auth",
    tokenUrl="https://your-idp.com/token",
    scopes={
        "rpa:execute": "Execute RPA workflows",
        "rpa:cancel": "Cancel RPA operations", 
        "rpa:admin": "Administrative access"
    }
)

class SecurityContext:
    def __init__(self, user_id: str, scopes: List[str], session_id: str):
        self.user_id = user_id
        self.scopes = scopes
        self.session_id = session_id

def validate_rpa_permissions(required_scope: str):
    def dependency(token: str = Depends(oauth2_scheme)):
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=["RS256"])
            user_scopes = payload.get("scopes", [])
            
            if required_scope not in user_scopes:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required: {required_scope}"
                )
            
            return SecurityContext(
                user_id=payload.get("sub"),
                scopes=user_scopes,
                session_id=payload.get("session_id")
            )
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
    return dependency
```

### 3. Secure Bot Factory Pattern

```python
# factories/secure_bot_factory.py
from abc import ABC, abstractmethod
from security.vault_client import VaultClient
from security.audit_logger import AuditLogger
import uuid
from typing import Dict, Any

class SecureBotFactory(ABC):
    def __init__(self, vault_client: VaultClient, audit_logger: AuditLogger):
        self.vault_client = vault_client
        self.audit_logger = audit_logger
    
    @abstractmethod
    def create_bot(self, provider: str, security_context: SecurityContext) -> 'SecureBot':
        pass
    
    def validate_bot_creation(self, provider: str, security_context: SecurityContext):
        """Validate if user can create bots for this provider"""
        required_scope = f"rpa:{provider}:execute"
        if required_scope not in security_context.scopes:
            raise SecurityError(f"User lacks permission for {provider} automation")

class OctotelSecureBotFactory(SecureBotFactory):
    def create_bot(self, provider: str, security_context: SecurityContext) -> 'OctotelSecureBot':
        self.validate_bot_creation(provider, security_context)
        
        # Get credentials with limited scope
        credentials = self.vault_client.get_bot_credentials(provider)
        
        # Create execution context with audit trail
        execution_id = str(uuid.uuid4())
        
        self.audit_logger.log_bot_creation(
            bot_type="octotel",
            user_id=security_context.user_id,
            execution_id=execution_id,
            session_id=security_context.session_id
        )
        
        return OctotelSecureBot(
            credentials=credentials,
            execution_id=execution_id,
            security_context=security_context,
            audit_logger=self.audit_logger
        )
```

### 4. Secure Automation Classes

```python
# secure_validation.py - Updated validation with security
from security.auth import SecurityContext
from security.audit_logger import AuditLogger
import time
from typing import Dict, Any

class SecureOctotelValidation:
    def __init__(self, credentials: Dict, execution_id: str, 
                 security_context: SecurityContext, audit_logger: AuditLogger):
        self.credentials = credentials
        self.execution_id = execution_id
        self.security_context = security_context
        self.audit_logger = audit_logger
        self.session_timeout = 300  # 5 minutes
        
    def validate_circuit(self, request: ValidationRequest) -> ValidationResult:
        start_time = time.time()
        
        try:
            # Log operation start
            self.audit_logger.log_operation_start(
                operation="validation",
                circuit_number=request.circuit_number,
                user_id=self.security_context.user_id,
                execution_id=self.execution_id
            )
            
            # Input validation and sanitization
            sanitized_circuit = self._sanitize_circuit_number(request.circuit_number)
            
            # Session timeout check
            self._check_session_timeout(start_time)
            
            # Execute validation with security wrapper
            result = self._execute_secure_validation(sanitized_circuit)
            
            # Log successful completion
            self.audit_logger.log_operation_success(
                operation="validation",
                circuit_number=sanitized_circuit,
                execution_time=time.time() - start_time,
                execution_id=self.execution_id
            )
            
            return result
            
        except Exception as e:
            # Log security incident
            self.audit_logger.log_security_incident(
                operation="validation",
                error=str(e),
                user_id=self.security_context.user_id,
                execution_id=self.execution_id
            )
            raise
    
    def _sanitize_circuit_number(self, circuit_number: str) -> str:
        """Sanitize circuit number to prevent injection attacks"""
        import re
        # Allow only alphanumeric characters and common separators
        if not re.match(r'^[A-Za-z0-9\-_]{3,20}$', circuit_number):
            raise SecurityError("Invalid circuit number format")
        return circuit_number.strip()
    
    def _check_session_timeout(self, start_time: float):
        """Check if session has exceeded timeout"""
        if time.time() - start_time > self.session_timeout:
            raise SecurityError("Session timeout exceeded")
```

### 5. Secure Cancellation with Fixed Values

```python
# secure_cancellation.py - Updated with security and fixed values
class SecureOctotelCancellation:
    # Security-hardened cancellation reasons
    ALLOWED_CANCELLATION_REASONS = [
        "Affordability",
        "Customer Service ISP", 
        "Changed FNO",
        "Non-payment",
        "Relocation",
        "Other"
    ]
    
    # Fixed cancellation reason as per requirements
    FIXED_CANCELLATION_REASON = "Customer Service ISP"
    FIXED_CANCELLATION_COMMENT = "Bot cancellation"
    
    def __init__(self, credentials: Dict, execution_id: str, 
                 security_context: SecurityContext, audit_logger: AuditLogger):
        self.credentials = credentials
        self.execution_id = execution_id
        self.security_context = security_context
        self.audit_logger = audit_logger
        
    def cancel_service(self, request: CancellationRequest) -> CancellationResult:
        try:
            # Validate cancellation permissions
            if "rpa:cancel" not in self.security_context.scopes:
                raise SecurityError("User lacks cancellation permissions")
            
            # Override any user-provided reason/comment with fixed values
            secure_request = CancellationRequest(
                job_id=request.job_id,
                circuit_number=self._sanitize_circuit_number(request.circuit_number),
                solution_id=self._sanitize_solution_id(request.solution_id),
                requested_date=request.requested_date,
                # Force fixed values for security
                reason=self.FIXED_CANCELLATION_REASON,
                comment=f"{self.FIXED_CANCELLATION_COMMENT}. Ref: {request.solution_id}"
            )
            
            # Log cancellation attempt
            self.audit_logger.log_cancellation_attempt(
                circuit_number=secure_request.circuit_number,
                user_id=self.security_context.user_id,
                execution_id=self.execution_id,
                reason=self.FIXED_CANCELLATION_REASON
            )
            
            # Execute secure cancellation
            result = self._execute_secure_cancellation(secure_request)
            
            # Log completion
            self.audit_logger.log_cancellation_complete(
                circuit_number=secure_request.circuit_number,
                success=result.cancellation_submitted,
                release_reference=result.release_reference,
                execution_id=self.execution_id
            )
            
            return result
            
        except Exception as e:
            self.audit_logger.log_security_incident(
                operation="cancellation",
                error=str(e),
                user_id=self.security_context.user_id,
                execution_id=self.execution_id
            )
            raise
```

## Phase 2: System-Wide Security Enhancements

### 1. Secure API Endpoints

```python
# Updated orchestrator.py endpoints with security
from security.auth import validate_rpa_permissions

@app.post("/jobs", response_model=Job)
async def create_job_endpoint(
    job: JobCreate,
    background_tasks: BackgroundTasks,
    security_context: SecurityContext = Depends(validate_rpa_permissions("rpa:execute"))
):
    """Create a new job with security validation"""
    
    # Validate provider access
    provider_scope = f"rpa:{job.provider}:execute"
    if provider_scope not in security_context.scopes:
        raise HTTPException(
            status_code=403,
            detail=f"User lacks permission for {job.provider} operations"
        )
    
    # Sanitize job parameters
    sanitized_params = sanitize_job_parameters(job.parameters)
    
    # Create job with security context
    job_dict = db.create_secure_job(
        provider=job.provider,
        action=job.action,
        parameters=sanitized_params,
        user_id=security_context.user_id,
        session_id=security_context.session_id,
        priority=job.priority
    )
    
    return Job(**job_dict)

@app.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: int,
    security_context: SecurityContext = Depends(validate_rpa_permissions("rpa:cancel"))
):
    """Cancel a job with proper authorization"""
    
    # Check if user owns the job or has admin rights
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if (job["user_id"] != security_context.user_id and 
        "rpa:admin" not in security_context.scopes):
        raise HTTPException(status_code=403, detail="Cannot cancel job owned by another user")
    
    # Proceed with cancellation...
```

### 2. Enhanced Input Validation

```python
# security/input_validator.py
import re
from typing import Any, Dict
from pydantic import BaseModel, validator

class SecureJobParameters(BaseModel):
    job_id: str
    circuit_number: str
    solution_id: Optional[str] = None
    
    @validator('circuit_number')
    def validate_circuit_number(cls, v):
        if not re.match(r'^[A-Za-z0-9\-_]{3,20}$', v):
            raise ValueError('Invalid circuit number format')
        return v.strip().upper()
    
    @validator('solution_id')
    def validate_solution_id(cls, v):
        if v and not re.match(r'^[A-Za-z0-9\-_]{3,50}$', v):
            raise ValueError('Invalid solution ID format')
        return v.strip() if v else None
    
    @validator('job_id')
    def validate_job_id(cls, v):
        if not re.match(r'^[A-Za-z0-9\-_]{5,100}$', v):
            raise ValueError('Invalid job ID format')
        return v.strip()

def sanitize_job_parameters(params: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize job parameters to prevent injection attacks"""
    try:
        validated = SecureJobParameters(**params)
        return validated.dict()
    except Exception as e:
        raise SecurityError(f"Parameter validation failed: {e}")
```

### 3. Audit Logging System

```python
# security/audit_logger.py
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

class AuditLogger:
    def __init__(self):
        self.logger = logging.getLogger("audit")
        handler = logging.FileHandler("logs/audit.log")
        formatter = logging.Formatter(
            '%(asctime)s [AUDIT] %(message)s'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
    
    def log_operation_start(self, operation: str, circuit_number: str, 
                          user_id: str, execution_id: str):
        audit_data = {
            "event": "operation_start",
            "operation": operation,
            "circuit_number": circuit_number,
            "user_id": user_id,
            "execution_id": execution_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.logger.info(json.dumps(audit_data))
    
    def log_security_incident(self, operation: str, error: str, 
                            user_id: str, execution_id: str):
        incident_data = {
            "event": "security_incident",
            "operation": operation,
            "error": error,
            "user_id": user_id,
            "execution_id": execution_id,
            "severity": "HIGH",
            "timestamp": datetime.utcnow().isoformat()
        }
        self.logger.error(json.dumps(incident_data))
        
        # Send alert to security team
        self._send_security_alert(incident_data)
    
    def _send_security_alert(self, incident_data: Dict):
        """Send immediate alert for security incidents"""
        # Implementation for alerting system
        pass
```

### 4. Secure Database Operations

```python
# Updated db.py with security enhancements
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
import uuid

class SecureJobQueue(Base):
    __tablename__ = "secure_job_queue"
    
    id = Column(Integer, primary_key=True)
    job_id = Column(String(100), unique=True, nullable=False)
    user_id = Column(String(100), nullable=False)  # Track job owner
    session_id = Column(String(100), nullable=False)  # Track session
    provider = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    parameters_encrypted = Column(Text)  # Encrypted parameters
    encryption_key_id = Column(String(100))  # Key rotation support
    created_at = Column(DateTime, default=datetime.utcnow)
    
def create_secure_job(provider: str, action: str, parameters: Dict,
                     user_id: str, session_id: str, priority: int = 0):
    """Create job with encryption and audit trail"""
    
    # Encrypt sensitive parameters
    encrypted_params, key_id = encrypt_parameters(parameters)
    
    job_data = {
        'job_id': str(uuid.uuid4()),
        'user_id': user_id,
        'session_id': session_id,
        'provider': provider,
        'action': action,
        'parameters_encrypted': encrypted_params,
        'encryption_key_id': key_id,
        'priority': priority,
        'status': 'pending'
    }
    
    with db_session() as session:
        job = SecureJobQueue(**job_data)
        session.add(job)
        session.commit()
        
        # Log job creation
        audit_logger.log_job_creation(job_data)
        
        return to_dict(job)
```

### 5. Network Security Middleware

```python
# security/middleware.py
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Add security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, calls_per_minute: int = 60):
        super().__init__(app)
        self.calls_per_minute = calls_per_minute
        self.clients = {}
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        current_time = time.time()
        
        # Clean old entries
        self.clients = {
            ip: calls for ip, calls in self.clients.items()
            if any(call_time > current_time - 60 for call_time in calls)
        }
        
        # Check rate limit
        if client_ip in self.clients:
            recent_calls = [
                call_time for call_time in self.clients[client_ip]
                if call_time > current_time - 60
            ]
            if len(recent_calls) >= self.calls_per_minute:
                return Response(
                    content="Rate limit exceeded",
                    status_code=429
                )
            self.clients[client_ip] = recent_calls + [current_time]
        else:
            self.clients[client_ip] = [current_time]
        
        return await call_next(request)
```

## Phase 3: Implementation Timeline

### Week 1-2: Foundation
- [ ] Set up HashiCorp Vault
- [ ] Implement OAuth2/OIDC integration
- [ ] Create secure credential management
- [ ] Update configuration system

### Week 3-4: Core Security
- [ ] Implement RBAC system
- [ ] Create secure bot factory pattern
- [ ] Add input validation and sanitization
- [ ] Set up audit logging

### Week 5-6: Automation Updates
- [ ] Update validation.py with security wrapper
- [ ] Update cancellation.py with fixed values
- [ ] Implement secure browser automation
- [ ] Add session management

### Week 7-8: System Integration
- [ ] Update orchestrator.py with secure endpoints
- [ ] Implement secure database operations
- [ ] Add network security middleware
- [ ] Complete testing and documentation

## Phase 4: Ongoing Security Measures

### Monthly Tasks
- [ ] Rotate encryption keys
- [ ] Update security dependencies
- [ ] Review audit logs
- [ ] Conduct security scans

### Quarterly Tasks
- [ ] Penetration testing
- [ ] RBAC policy review
- [ ] Security training
- [ ] Compliance audits

## Key Security Benefits

1. **Zero-Trust Architecture**: Every operation requires explicit authentication and authorization
2. **Credential Security**: No hardcoded credentials, automatic rotation
3. **Audit Trail**: Complete logging of all security-relevant events
4. **Input Validation**: Protection against injection attacks
5. **Session Management**: Timeout and session tracking
6. **Fixed Configuration**: Hardcoded cancellation reasons prevent manipulation
7. **Encryption**: Sensitive data encrypted at rest and in transit
8. **Rate Limiting**: Protection against abuse and DoS attacks

This security implementation maintains the existing functionality while adding enterprise-grade security controls that are essential for production RPA systems handling financial and customer data.