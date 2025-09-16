# RPA System Health Management & Monitoring Endpoints

## Overview

This document provides comprehensive API specifications for health monitoring and troubleshooting endpoints in the RPA orchestration system. These endpoints provide essential visibility into system health, job execution metrics, and operational status across both the orchestrator and worker services.

**System Architecture:**
- **Orchestrator Service** (Default Port 8620): Manages job scheduling, distribution, and overall system coordination
- **Worker Service** (Default Port 8621): Executes automation jobs for various FNO (Fixed Network Operator) providers

---

## Complete Endpoint Reference

### Orchestrator Service (Port 8620)

| Method | Endpoint | Purpose | Authentication | Response Type |
|--------|----------|---------|----------------|---------------|
| GET | `/health` | Basic health check | None | JSON |
| GET | `/metrics` | System metrics and performance | None | JSON |
| GET | `/scheduler` | Scheduler status and jobs | None | JSON |
| POST | `/scheduler/reset` | Reset scheduler configuration | JWT Required | JSON |
| POST | `/process` | Manual job processing trigger | JWT Required | JSON |
| POST | `/recover` | Recover stale jobs | JWT Required | JSON |
| GET | `/jobs/{job_id}/screenshots` | Job audit evidence | JWT Required | JSON |
| POST | `/privacy/data-request` | POPIA data requests | None | JSON |  
| GET | `/privacy/notice` | Privacy notice | None | JSON |
| POST | `/token` | Obtain JWT authentication token | None | JSON |

### Worker Service (Port 8621)

| Method | Endpoint | Purpose | IP Validation | Response Type |
|--------|----------|---------|---------------|---------------|
| GET | `/status` | Comprehensive worker status | Yes | JSON |
| GET | `/health` | Basic health check | Yes | JSON |
| GET | `/status/{job_id}` | Individual job status | Yes | JSON |
| POST | `/execute` | Execute automation job | Yes | JSON |

---

## Basic Health Check Endpoints

### Orchestrator Health Check
**Endpoint:** `GET /health`  
**Authentication:** None required  
**Purpose:** Simple health verification for load balancers and monitoring systems

**Request:**
```bash
curl -X GET "http://localhost:8620/health"
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-08-01T10:30:00.000Z"
}
```

**Response Fields:**
- `status`: Always `"healthy"` if service is responsive
- `timestamp`: ISO 8601 timestamp of the response

---

### Worker Health Check
**Endpoint:** `GET /health`  
**Authentication:** IP whitelist validation  
**Purpose:** Basic worker service health verification

**Request:**
```bash
curl -X GET "http://localhost:8621/health"
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-08-01T10:30:00.000Z",
  "active_jobs": 2
}
```

**Response Fields:**
- `status`: Always `"healthy"` if worker is responsive
- `timestamp`: ISO 8601 timestamp
- `active_jobs`: Number of currently executing jobs

---

## System Metrics Endpoints

### Comprehensive System Metrics
**Endpoint:** `GET /metrics`  
**Authentication:** None required  
**Purpose:** Complete system performance and job execution statistics

**Request:**
```bash
curl -X GET "http://localhost:8620/metrics"
```

**Response:**
```json
{
  "metrics": [
    {
      "timestamp": "2025-08-01T10:00:00Z",
      "queued_jobs": 15,
      "running_jobs": 3,
      "completed_jobs": 142,
      "failed_jobs": 8
    },
    {
      "timestamp": "2025-08-01T09:55:00Z",
      "queued_jobs": 18,
      "running_jobs": 2,
      "completed_jobs": 140,
      "failed_jobs": 8
    }
  ],
  "averages": {
    "queued_jobs": 12.5,
    "running_jobs": 2.8,
    "completed_jobs": 140.2,
    "failed_jobs": 7.1
  },
  "current": {
    "status": "online",
    "uptime": "2 days, 14:32:15",
    "queued_jobs": 15,
    "running_jobs": 3,
    "completed_jobs": 142,
    "failed_jobs": 8,
    "workers": {
      "http://localhost:8621/execute": "online"
    },
    "version": "0.9.0"
  }
}
```

**Key Response Fields:**

**metrics** (Array): Historical data points
- `timestamp`: When metrics were collected
- `queued_jobs`: Jobs waiting for processing
- `running_jobs`: Currently executing jobs  
- `completed_jobs`: Total successful jobs
- `failed_jobs`: Total failed jobs

**averages** (Object): Calculated averages for trends
- All fields averaged over the metrics array

**current** (Object): Real-time system state
- `status`: `"online"` or `"degraded"`
- `uptime`: Human-readable uptime string
- `workers`: Object with worker endpoint → status mapping
- `version`: System version

**Business Value:** Provides insight into system throughput, bottlenecks, and overall automation success rates.

---

### Worker Detailed Status
**Endpoint:** `GET /status`  
**Authentication:** IP whitelist validation  
**Purpose:** Comprehensive worker capabilities and performance metrics

**Request:**
```bash
curl -X GET "http://localhost:8621/status"
```

**Response:**
```json
{
  "status": "online",
  "version": "1.0.0",
  "uptime": "1 day, 8:45:22",
  "hostname": "worker-01",
  "system": "Linux",
  "python_version": "3.9.7",
  "selenium_available": true,
  "providers": ["mfn", "osn", "octotel", "evotel"],
  "actions": {
    "mfn": ["validation", "cancellation"],
    "osn": ["validation", "cancellation"],
    "octotel": ["validation", "cancellation"],
    "evotel": ["validation", "cancellation"]
  },
  "job_stats": {
    "active": 2,
    "total": 156,
    "successful": 142,
    "failed": 12
  },
  "capacity": {
    "max_concurrent": 4,
    "current_load": 2
  }
}
```

**Key Information:**
- **providers**: Which FNO providers this worker can handle
- **actions**: Available automation actions per provider
- **capacity**: Current load vs maximum concurrent jobs
- **selenium_available**: Whether browser automation is functional

**Business Value:** Helps determine worker capacity, capabilities, and automation success rates.

---

## Troubleshooting Quick Reference

| Issue | Check Endpoint | Action | Expected Fix |
|-------|---------------|---------|--------------|
| Jobs not processing | `GET /scheduler` | Verify poll_job_queue is running | Use `POST /scheduler/reset` |
| Worker offline | `GET /status` (worker) | Check worker service health | Restart worker service |
| High failure rate | `GET /metrics` | Review failed_jobs trend | Investigate automation modules |
| Stuck jobs | `GET /metrics` | Check running_jobs vs queued_jobs | Use `POST /recover` |
| Scheduler issues | `GET /scheduler` | Check running status | Use `POST /scheduler/reset` |
| Authentication failures | Check logs | Monitor token endpoint | Refresh JWT tokens |
| IP access denied | Check logs | Review authorized IPs | Update IP whitelist |

---

## Error Handling & Response Codes

### Standard HTTP Status Codes
- **200 OK**: Request successful
- **400 Bad Request**: Invalid request parameters
- **401 Unauthorized**: Authentication required/failed
- **403 Forbidden**: IP not authorized (worker endpoints)
- **404 Not Found**: Resource not found
- **500 Internal Server Error**: Server-side error

### Common Error Response Format
```json
{
  "detail": "Error description",
  "error_type": "ValidationError",
  "timestamp": "2025-08-01T10:30:00.000Z"
}
```

### Authentication Error Examples

**Invalid Credentials:**
```bash
curl -X POST "http://localhost:8620/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=wrong&password=wrong"
```

**Response:**
```json
{
  "detail": "Incorrect username or password"
}
```

**Expired/Invalid Token:**
```bash
curl -X POST "http://localhost:8620/process" \
  -H "Authorization: Bearer invalid_token"
```

**Response:**
```json
{
  "detail": "Could not validate credentials"
}
```

### Worker IP Validation Error

**Unauthorized IP:**
```json
{
  "detail": "Unauthorized IP address"
}
```

---

## Troubleshooting Endpoints

### Scheduler Status Check
**Endpoint:** `GET /scheduler`  
**Authentication:** None required  
**Purpose:** Monitor background task scheduler health

**Request:**
```bash
curl -X GET "http://localhost:8620/scheduler"
```

**Response:**
```json
{
  "running": true,
  "job_count": 5,
  "jobs": [
    {
      "id": "poll_job_queue",
      "function": "poll_job_queue",
      "trigger": "interval[0:00:30]",
      "next_run": "2025-08-01T10:31:00.000Z"
    },
    {
      "id": "collect_metrics",
      "function": "collect_metrics",
      "trigger": "interval[0:05:00]",
      "next_run": "2025-08-01T10:35:00.000Z"
    },
    {
      "id": "cleanup_old_evidence",
      "function": "cleanup_old_evidence",
      "trigger": "cron",
      "next_run": "2025-08-02T02:00:00.000Z"
    },
    {
      "id": "recover_stale_jobs",
      "function": "recover_stale_jobs",
      "trigger": "interval[0:10:00]",
      "next_run": "2025-08-01T10:40:00.000Z"
    },
    {
      "id": "poll_worker_job_status",
      "function": "poll_worker_job_status",
      "trigger": "interval[0:00:30]",
      "next_run": "2025-08-01T10:31:15.000Z"
    }
  ]
}
```

**Critical Fields:**
- `running`: Boolean - scheduler operational status
- `job_count`: Number of scheduled background tasks
- `jobs[].next_run`: When each critical task will run next

**Alert Conditions:**
- `running: false` → Critical alert
- Missing `poll_job_queue` job → Jobs won't process
- Missing `collect_metrics` job → Metrics won't update

---

### Manual Job Processing Trigger
**Endpoint:** `POST /process`  
**Authentication:** JWT token required  
**Purpose:** Manually trigger job queue processing for troubleshooting

**Request:**
```bash
curl -X POST "http://localhost:8620/process" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Response:**
```json
{
  "status": "Job processing initiated"
}
```

**Use Case:** Emergency action when queue is stuck and jobs aren't processing automatically.

---

### Stale Job Recovery
**Endpoint:** `POST /recover`  
**Authentication:** JWT token required  
**Purpose:** Recover jobs stuck in processing state

**Request:**
```bash
curl -X POST "http://localhost:8620/recover" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Response:**
```json
{
  "status": "success",
  "recovered_jobs": 3
}
```

**Use Case:** Jobs stuck in "running" state due to worker crashes or network issues.

---

### Scheduler Reset
**Endpoint:** `POST /scheduler/reset`  
**Authentication:** JWT token required  
**Purpose:** Reset and reconfigure scheduler when it's malfunctioning

**Request:**
```bash
curl -X POST "http://localhost:8620/scheduler/reset" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Response:**
```json
{
  "status": "success",
  "message": "Scheduler reset and reconfigured successfully",
  "job_count": 5
}
```

**Use Case:** Emergency scheduler repair when background tasks stop running.

---

### Individual Job Status Tracking
**Endpoint:** `GET /status/{job_id}`  
**Authentication:** IP whitelist validation  
**Purpose:** Track specific job execution on worker

**Request:**
```bash
curl -X GET "http://localhost:8621/status/12345"
```

**Successful Job Response:**
```json
{
  "job_id": 12345,
  "status": "completed",
  "result": {
    "status": "success",
    "message": "Validation completed successfully",
    "details": {
      "provider": "mfn",
      "action": "validation",
      "circuit_number": "ABC123",
      "processing_time": "00:03:45"
    }
  },
  "start_time": "2025-08-01T10:15:00Z",
  "end_time": "2025-08-01T10:18:45Z"
}
```

**Failed Job Response:**
```json
{
  "job_id": 12346,
  "status": "failed",
  "result": {
    "error": "Portal login failed after 3 attempts",
    "error_type": "AuthenticationError",
    "details": {
      "provider": "osn",
      "action": "validation",
      "retry_count": 3
    }
  },
  "start_time": "2025-08-01T10:20:00Z",
  "end_time": "2025-08-01T10:25:30Z"
}
```

**Job Not Found Response:**
```json
{
  "job_id": 99999,
  "status": "not_found",
  "message": "No status information for job 99999"
}
```

**Status Values:**
- `"running"`: Job currently executing
- `"completed"`: Job finished successfully
- `"failed"`: Job encountered error
- `"not_found"`: Job not on this worker

---

### Authentication Token Endpoint
**Endpoint:** `POST /token`  
**Purpose:** Get authentication token for protected endpoints

**Request:**
```bash
curl -X POST "http://localhost:8620/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin"
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImV4cCI6MTY5MTc2MzYwMH0.signature",
  "token_type": "bearer"
}
```

**Token Usage:**
```bash
curl -X POST "http://localhost:8620/process" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Note:** Token expires after 60 minutes and must be refreshed.

---

## Security Considerations

### Authentication & Authorization

#### JWT Token Authentication (Orchestrator)
The orchestrator uses JWT (JSON Web Token) based authentication for most endpoints:

- **Token Endpoint**: `POST /token` - Obtain JWT token using OAuth2 password flow
- **Algorithm**: HS256 (configurable via `JWT_ALGORITHM`)
- **Token Expiration**: 60 minutes (configurable via `JWT_EXPIRATION_MINUTES`)
- **Secret Key**: Configured via `JWT_SECRET` environment variable

#### Permission System
- Currently implements minimal permission checking via `check_permission()` function
- All authenticated requests currently allowed (designed for future role-based access)
- Permission format: `"resource:action"` (e.g., `"job:create"`)

#### Default Credentials
- **Default Admin User**: `admin` / `admin` (configurable via environment variables)
- **Production Warning**: Change default credentials immediately in production
- Passwords hashed using bcrypt with salt rounds = 12

### Network Security

#### IP Address Validation (Worker Service)
Worker endpoints implement IP whitelisting for additional security:

```python
# Configured via AUTHORIZED_WORKER_IPS environment variable
AUTHORIZED_WORKER_IPS = ["127.0.0.1", "192.168.1.0/24"]
```

- Supports individual IPs and CIDR notation
- Returns HTTP 403 for unauthorized IP addresses
- Bypassed for localhost connections during development

#### SSL/TLS Configuration
Production deployments should use HTTPS:

```python
# Environment variables
SSL_CERT_PATH = "/path/to/certificate.pem"
SSL_KEY_PATH = "/path/to/private-key.pem"
```

- **Development Mode**: SSL disabled (`DEVELOPMENT_MODE=true`)
- **Production**: SSL enforced with TLS 1.2+ minimum
- **Certificate Validation**: Automatic validation of certificate files

#### CORS (Cross-Origin Resource Sharing)
Configurable CORS settings for web client integration:

```python
CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]
CORS_ALLOW_CREDENTIALS = true
```

### Data Security

#### Sensitive Data Handling
- **Screenshots**: May contain PII - stored with job-specific isolation
- **Job Parameters**: May contain customer identifiers - logged securely
- **Evidence Files**: Automatically cleaned up after retention period

#### Data Retention & Privacy
```python
# Configurable retention periods
SCREENSHOT_RETENTION_DAYS = 30  # Maximum retention for audit compliance
```

- **POPIA Compliance**: Automatic data deletion after retention period
- **Data Subject Requests**: Handled via `/privacy/data-request` endpoint
- **Contact**: Data protection officer contact via `DATA_PROTECTION_CONTACT`

### Security Monitoring

Monitor authentication-related metrics:
- Check orchestrator logs for `HTTP_401_UNAUTHORIZED` responses
- Monitor `/token` endpoint for failed login attempts
- Track IP address violations in worker logs

### Security Configuration

#### Required Security Environment Variables
```bash
# Authentication
JWT_SECRET="your-strong-secret-key-change-this-in-production"
ADMIN_USERNAME="your-admin-username"
ADMIN_PASSWORD="your-secure-password"

# Network Security
AUTHORIZED_WORKER_IPS='["192.168.1.100", "10.0.0.0/8"]'
CORS_ORIGINS='["https://your-frontend-domain.com"]'

# SSL/TLS
SSL_CERT_PATH="/path/to/certificate.pem"
SSL_KEY_PATH="/path/to/private-key.pem"

# Privacy Compliance
DATA_PROTECTION_CONTACT="dataprotection@yourcompany.com"
```

### Production Security Checklist
- [ ] Change default admin credentials
- [ ] Configure strong JWT secret key (minimum 256-bit)
- [ ] Enable SSL/TLS with valid certificates
- [ ] Restrict CORS origins to trusted domains
- [ ] Configure authorized worker IP addresses
- [ ] Set up log monitoring for security events
- [ ] Implement regular security log reviews

---

## Maintenance Operations

### Regular Maintenance Tasks

#### Daily Monitoring
- Check `/health` endpoints for service availability
- Review `/metrics` for unusual patterns or performance degradation
- Monitor failure rates and queue buildup
- Verify worker capacity and utilization

#### Weekly Maintenance
- Review `/scheduler` for any failed background jobs
- Analyze job success rates by provider
- Check log files for security incidents
- Verify SSL certificate expiration dates

#### Monthly Analysis
- Review system performance trends from `/metrics` historical data
- Analyze automation success rates and identify improvement areas
- Audit security logs for unauthorized access attempts
- Update and rotate authentication credentials if needed

### Emergency Procedures

#### System Unresponsive
1. Check orchestrator health: `GET /health`
2. Check worker health: `GET /health` on all workers
3. Review system logs for errors
4. Restart services if necessary

#### Jobs Not Processing
1. Check scheduler status: `GET /scheduler`
2. Verify background jobs are running
3. Manual trigger if needed: `POST /process`
4. Reset scheduler if critical: `POST /scheduler/reset`

#### Worker Issues
1. Check worker status: `GET /status`
2. Verify worker capacity and load
3. Check IP whitelist configuration
4. Restart worker service if offline

#### High Failure Rates
1. Review metrics: `GET /metrics`
2. Check individual job failures: `GET /status/{job_id}`
3. Identify patterns by provider or action type
4. Investigate automation module issues

### Scheduled Maintenance Windows

#### Background Job Schedule
- **Job Queue Polling**: Every 30 seconds
- **Metrics Collection**: Every 5 minutes
- **Stale Job Recovery**: Every 10 minutes
- **Evidence Cleanup**: Daily at 2:00 AM
- **Worker Status Polling**: Every 30 seconds

#### Maintenance Commands
```bash
# Check scheduler health
curl -X GET "http://localhost:8620/scheduler"

# Trigger manual job processing
curl -X POST "http://localhost:8620/process" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Recover stuck jobs
curl -X POST "http://localhost:8620/recover" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Reset scheduler (emergency only)
curl -X POST "http://localhost:8620/scheduler/reset" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### System Health Indicators

#### Green (Healthy)
- All `/health` endpoints return 200
- Scheduler running with all jobs scheduled
- Job failure rate < 5%
- Queue size reasonable (< 20 jobs)
- All workers online and responsive

#### Yellow (Warning)
- Intermittent worker connectivity issues
- Job failure rate between 5-10%
- Queue buildup (20-50 jobs)
- High worker utilization (> 80%)

#### Red (Critical)
- Orchestrator `/health` endpoint failing
- Scheduler not running
- Job failure rate > 10%
- No workers online
- Queue size > 50 jobs
- Authentication system failures

---

*Document Version: 3.0*  
*Target Audience: Business Analysts & Developers*  
*Last Updated: August 2025*  
*Next Review: Quarterly or when system changes are implemented*