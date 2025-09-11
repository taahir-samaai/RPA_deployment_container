#!/bin/bash
# Complete Self-Contained OpenShift RPA Deployment Script
# Replaces rpa-production-deployment.sh for fresh OpenShift installations
# Includes all Containerfiles, manifests, and configurations embedded

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="rpa-system"
PROJECT_NAME="rpa-system"
SOURCE_DIR=""
ENVIRONMENT_TYPE="production"
DRY_RUN=false
BUILD_DIR=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Logging functions
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
    log "INFO: $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
    log "SUCCESS: $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    log "WARNING: $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    log "ERROR: $1"
    exit 1
}

section() {
    echo -e "\n${CYAN}================================================${NC}"
    echo -e "${CYAN} $1 ${NC}"
    echo -e "${CYAN}================================================${NC}"
    log "SECTION: $1"
}

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Complete fresh OpenShift RPA installation with embedded components.

OPTIONS:
    -s, --source-dir DIR       Path to RPA source code directory (required)
    -e, --environment TYPE     Environment type (production, staging, development) [default: production]
    -n, --namespace NAME       OpenShift namespace [default: rpa-system]
    -r, --dry-run             Show what would be deployed without applying
    -h, --help                Show this help message

EXAMPLES:
    $0 -s /path/to/rpa-source-code
    $0 -s ./rpa_botfarm -e production -n rpa-prod
    $0 -s /opt/rpa-system -e staging --dry-run

EXPECTED SOURCE DIRECTORY STRUCTURE:
    Your source directory should contain (based on working EC2 Containerfiles):
    
    /your/source/directory/
    ├── rpa_botfarm/
    │   ├── orchestrator.py         ← Main orchestrator service
    │   ├── worker.py              ← Main worker service
    │   ├── config.py              ← Shared configuration
    │   ├── auth.py                ← Authentication (orchestrator)
    │   ├── db.py                  ← Database models (orchestrator)
    │   ├── models.py              ← Data models (both)
    │   ├── errors.py              ← Error handling (both)
    │   ├── health_reporter.py     ← Health reporting (both)
    │   ├── rate_limiter.py        ← Rate limiting (orchestrator)
    │   ├── conjur_client.py       ← External integration (orchestrator)
    │   ├── totp_generator.py      ← 2FA support (worker)
    │   ├── test_framework.py      ← Testing utilities (worker)
    │   ├── automations/           ← Automation modules (worker)
    │   │   ├── mfn/
    │   │   │   ├── validation.py
    │   │   │   └── cancellation.py
    │   │   ├── osn/
    │   │   ├── octotel/
    │   │   └── evotel/
    │   └── drivers/               ← Browser drivers (worker)
    └── requirements.txt           ← Python dependencies (optional)

SOURCE CODE REQUIREMENTS:
    Your source directory should contain:
    - rpa_botfarm/orchestrator.py
    - rpa_botfarm/worker.py
    - rpa_botfarm/automations/ (directory)
    - automations/ (provider modules)
    - requirements.txt (will be created if missing)

EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--source-dir)
                SOURCE_DIR="$2"
                shift 2
                ;;
            -e|--environment)
                ENVIRONMENT_TYPE="$2"
                shift 2
                ;;
            -n|--namespace)
                NAMESPACE="$2"
                PROJECT_NAME="$2"
                shift 2
                ;;
            -r|--dry-run)
                DRY_RUN=true
                shift
                ;;
            -h|--help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1. Use -h for help."
                ;;
        esac
    done

    if [[ -z "$SOURCE_DIR" ]]; then
        error "Source directory is required. Use: $0 -s /path/to/rpa-source-code"
    fi

    if [[ ! -d "$SOURCE_DIR" ]]; then
        error "Source directory does not exist: $SOURCE_DIR"
    fi

    SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
    
    info "Using source directory: $SOURCE_DIR"
    info "Target environment: $ENVIRONMENT_TYPE"
    info "OpenShift namespace: $NAMESPACE"
    if [[ "$DRY_RUN" == true ]]; then
        info "DRY RUN MODE - No changes will be applied"
    fi
}

# Check prerequisites
check_prerequisites() {
    section "CHECKING PREREQUISITES"
    
    # Check oc command
    if ! command -v oc >/dev/null 2>&1; then
        error "OpenShift CLI 'oc' is required but not installed"
    fi
    
    # Check OpenShift connection
    if ! oc whoami >/dev/null 2>&1; then
        error "Not logged into OpenShift. Run 'oc login' first"
    fi
    
    # Check source code structure
    local critical_files=("rpa_botfarm/orchestrator.py" "rpa_botfarm/worker.py")
    local missing_files=()
    
    for file in "${critical_files[@]}"; do
        if [[ ! -f "$SOURCE_DIR/$file" ]]; then
            missing_files+=("$file")
        fi
    done
    
    if [[ ${#missing_files[@]} -gt 0 ]]; then
        error "Missing critical files in source directory: ${missing_files[*]}"
    fi
    
    # Check cluster admin privileges (for SCC)
    if ! oc auth can-i create securitycontextconstraints 2>/dev/null; then
        warning "No cluster admin privileges. SecurityContextConstraints may need manual creation"
    fi
    
    # Check storage classes
    if ! oc get storageclass >/dev/null 2>&1; then
        warning "Could not list storage classes. Verify cluster storage configuration"
    fi
    
    local current_project=$(oc project -q 2>/dev/null || echo "")
    info "Current OpenShift project: ${current_project:-"none"}"
    info "Connected to cluster: $(oc cluster-info | head -1 | cut -d' ' -f6)"
    
    success "Prerequisites check completed"
}

# Detect available storage classes
detect_storage_classes() {
    section "DETECTING STORAGE CLASSES"
    
    # Get available storage classes
    local storage_classes=($(oc get storageclass --no-headers -o custom-columns=":metadata.name" 2>/dev/null || echo ""))
    
    if [[ ${#storage_classes[@]} -eq 0 ]]; then
        warning "No storage classes found. Using default storage."
        SINGLE_STORAGE_CLASS=""
        SHARED_STORAGE_CLASS=""
        return
    fi
    
    info "Available storage classes: ${storage_classes[*]}"
    
    # Auto-detect suitable storage classes
    SINGLE_STORAGE_CLASS=""
    SHARED_STORAGE_CLASS=""
    
    # Look for common single-access storage patterns
    for sc in "${storage_classes[@]}"; do
        if [[ "$sc" =~ (gp3|gp2|ebs|disk|block|rbd) ]]; then
            SINGLE_STORAGE_CLASS="$sc"
            break
        fi
    done
    
    # Look for common shared storage patterns
    for sc in "${storage_classes[@]}"; do
        if [[ "$sc" =~ (efs|nfs|file|shared|cephfs) ]]; then
            SHARED_STORAGE_CLASS="$sc"
            break
        fi
    done
    
    # Fallback to first available if not found
    if [[ -z "$SINGLE_STORAGE_CLASS" ]]; then
        SINGLE_STORAGE_CLASS="${storage_classes[0]}"
        warning "Using fallback storage class for single-access: $SINGLE_STORAGE_CLASS"
    fi
    
    if [[ -z "$SHARED_STORAGE_CLASS" ]]; then
        SHARED_STORAGE_CLASS="${storage_classes[0]}"
        warning "Using fallback storage class for shared storage: $SHARED_STORAGE_CLASS"
    fi
    
    info "Selected single-access storage: $SINGLE_STORAGE_CLASS"
    info "Selected shared storage: $SHARED_STORAGE_CLASS"
    
    success "Storage classes detected and configured"
}

# Generate environment-specific configurations
generate_environment_configs() {
    section "GENERATING ENVIRONMENT-SPECIFIC CONFIGURATIONS"
    
    # Set environment-specific values
    case "$ENVIRONMENT_TYPE" in
        "production")
            WORKER_REPLICAS=5
            WORKER_MEMORY="2Gi"
            WORKER_CPU_REQUEST="1000m"
            WORKER_CPU_LIMIT="1000m"
            ORCHESTRATOR_MEMORY="1Gi"
            ORCHESTRATOR_CPU_REQUEST="500m"
            ORCHESTRATOR_CPU_LIMIT="1000m"
            WORKER_TIMEOUT="600"
            JOB_POLL_INTERVAL="10"
            LOG_LEVEL="INFO"
            HPA_MIN_REPLICAS=5
            HPA_MAX_REPLICAS=10
            ;;
        "staging")
            WORKER_REPLICAS=3
            WORKER_MEMORY="1Gi"
            WORKER_CPU_REQUEST="500m"
            WORKER_CPU_LIMIT="1000m"
            ORCHESTRATOR_MEMORY="512Mi"
            ORCHESTRATOR_CPU_REQUEST="250m"
            ORCHESTRATOR_CPU_LIMIT="500m"
            WORKER_TIMEOUT="300"
            JOB_POLL_INTERVAL="30"
            LOG_LEVEL="INFO"
            HPA_MIN_REPLICAS=2
            HPA_MAX_REPLICAS=5
            ;;
        "development")
            WORKER_REPLICAS=2
            WORKER_MEMORY="512Mi"
            WORKER_CPU_REQUEST="250m"
            WORKER_CPU_LIMIT="500m"
            ORCHESTRATOR_MEMORY="256Mi"
            ORCHESTRATOR_CPU_REQUEST="100m"
            ORCHESTRATOR_CPU_LIMIT="250m"
            WORKER_TIMEOUT="180"
            JOB_POLL_INTERVAL="60"
            LOG_LEVEL="DEBUG"
            HPA_MIN_REPLICAS=1
            HPA_MAX_REPLICAS=3
            ;;
        *)
            error "Unknown environment type: $ENVIRONMENT_TYPE"
            ;;
    esac
    
    info "Environment: $ENVIRONMENT_TYPE"
    info "Worker replicas: $WORKER_REPLICAS"
    info "Worker memory: $WORKER_MEMORY"
    info "Orchestrator memory: $ORCHESTRATOR_MEMORY"
    info "Worker timeout: ${WORKER_TIMEOUT}s"
    info "Auto-scaling: $HPA_MIN_REPLICAS-$HPA_MAX_REPLICAS replicas"
    
    success "Environment configurations generated"
}

# Prepare build directory with source code
prepare_build_directory() {
    section "PREPARING BUILD DIRECTORY WITH SOURCE CODE"
    
    # Create temporary build directory
    BUILD_DIR="/tmp/rpa-build-$$"
    mkdir -p "$BUILD_DIR"
    
    info "Created build directory: $BUILD_DIR"
    
    # Copy source code
    info "Copying source code from: $SOURCE_DIR"
    cp -r "$SOURCE_DIR"/* "$BUILD_DIR/"
    
    # Create requirements.txt if missing
    if [[ ! -f "$BUILD_DIR/requirements.txt" ]]; then
        info "Creating requirements.txt..."
        cat > "$BUILD_DIR/requirements.txt" << 'EOF'
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic==2.5.0
selenium==4.15.2
requests==2.31.0
httpx==0.25.2
Pillow==10.1.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.6
SQLAlchemy==2.0.23
APScheduler==3.10.4
tenacity==8.2.3
python-dotenv==1.0.0
jinja2==3.1.2
aiofiles==23.2.1
psutil==5.9.6
python-dateutil==2.8.2
pytz==2023.3
EOF
    fi
    
    # Create directory structure
    mkdir -p "$BUILD_DIR/containers/orchestrator"
    mkdir -p "$BUILD_DIR/containers/worker"
    
    success "Build directory prepared with source code"
}

# Create embedded Containerfiles
create_embedded_containerfiles() {
    section "CREATING EMBEDDED CONTAINERFILES"
    
    info "Creating orchestrator Containerfile..."
    cat > "$BUILD_DIR/containers/orchestrator/Containerfile" << 'EOF'
FROM registry.redhat.io/ubi9/python-311:latest

USER root
RUN dnf update -y && \
    dnf install -y sqlite gcc python3-devel curl wget jq procps-ng && \
    dnf clean all

RUN useradd -m -u 1001 rpauser && mkdir -p /app && chown -R rpauser:rpauser /app

USER rpauser
WORKDIR /app

COPY requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt

COPY --chown=rpauser:rpauser . .
RUN mkdir -p data/{db,logs,screenshots,evidence} logs temp

ENV PYTHONPATH=/app
ENV PATH="${PATH}:/home/rpauser/.local/bin"

EXPOSE 8620
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8620/health || exit 1

CMD ["python", "rpa_botfarm/orchestrator.py"]
EOF

    info "Creating worker Containerfile..."
    cat > "$BUILD_DIR/containers/worker/Containerfile" << 'EOF'
FROM registry.redhat.io/ubi9/python-311:latest

USER root
RUN dnf update -y && dnf install -y \
    chromium \
    chromium-driver \
    sqlite \
    gcc \
    python3-devel \
    curl \
    wget \
    jq \
    procps-ng \
    && dnf clean all

RUN useradd -m -u 1001 rpauser && mkdir -p /app && chown -R rpauser:rpauser /app

USER rpauser
WORKDIR /app

COPY requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt

COPY --chown=rpauser:rpauser . .
RUN mkdir -p data/{logs,screenshots,evidence} worker_data logs temp

ENV PYTHONPATH=/app
ENV PATH="${PATH}:/home/rpauser/.local/bin"
ENV CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
ENV CHROME_BINARY_PATH=/usr/bin/chromium-browser
ENV HEADLESS=true

EXPOSE 8621
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8621/health || exit 1

CMD ["python", "rpa_botfarm/worker.py"]
EOF

    success "Embedded Containerfiles created"
}

# Build container images in OpenShift
build_images_in_openshift() {
    section "BUILDING CONTAINER IMAGES IN OPENSHIFT"
    
    cd "$BUILD_DIR"
    
    # Create build configs if they don't exist
    if ! oc get bc rpa-orchestrator -n "$NAMESPACE" >/dev/null 2>&1; then
        info "Creating orchestrator build configuration..."
        if [[ "$DRY_RUN" == false ]]; then
            oc new-build --name rpa-orchestrator --binary --strategy=docker \
                --dockerfile-path=containers/orchestrator/Containerfile -n "$NAMESPACE"
        fi
    fi
    
    if ! oc get bc rpa-worker -n "$NAMESPACE" >/dev/null 2>&1; then
        info "Creating worker build configuration..."
        if [[ "$DRY_RUN" == false ]]; then
            oc new-build --name rpa-worker --binary --strategy=docker \
                --dockerfile-path=containers/worker/Containerfile -n "$NAMESPACE"
        fi
    fi
    
    # Build orchestrator image
    info "Building orchestrator image from source..."
    if [[ "$DRY_RUN" == false ]]; then
        oc start-build rpa-orchestrator --from-dir=. --follow -n "$NAMESPACE"
        
        # Verify build success
        if ! oc get imagestream rpa-orchestrator -n "$NAMESPACE" >/dev/null 2>&1; then
            error "Orchestrator image build failed"
        fi
    else
        info "DRY RUN: Would build orchestrator from $BUILD_DIR"
    fi
    
    # Build worker image
    info "Building worker image from source..."
    if [[ "$DRY_RUN" == false ]]; then
        oc start-build rpa-worker --from-dir=. --follow -n "$NAMESPACE"
        
        # Verify build success
        if ! oc get imagestream rpa-worker -n "$NAMESPACE" >/dev/null 2>&1; then
            error "Worker image build failed"
        fi
    else
        info "DRY RUN: Would build worker from $BUILD_DIR"
    fi
    
    success "Container images built successfully"
}

# Create complete embedded OpenShift manifests
create_embedded_manifests() {
    section "CREATING EMBEDDED OPENSHIFT MANIFESTS"
    
    local manifests_file="/tmp/rpa-manifests-${NAMESPACE}-$$.yaml"
    
    # Generate secrets
    local jwt_secret=$(openssl rand -hex 32)
    local admin_password=$(openssl rand -base64 16)
    
    # Save admin password
    echo "$admin_password" > "$HOME/.rpa-admin-password"
    chmod 600 "$HOME/.rpa-admin-password"
    
    info "Generated admin password: $admin_password"
    info "Saved to: $HOME/.rpa-admin-password"
    
    # Create complete manifests with all embedded resources
    cat > "$manifests_file" << EOF
# ================================================================
# Complete OpenShift RPA System Deployment Manifests
# Environment: $ENVIRONMENT_TYPE
# Generated: $(date)
# Source: $SOURCE_DIR
# ================================================================

---
# Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system
    app.kubernetes.io/component: automation
    environment: $ENVIRONMENT_TYPE

---
# ConfigMap for Orchestrator Configuration
apiVersion: v1
kind: ConfigMap
metadata:
  name: orchestrator-config
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-orchestrator
    app.kubernetes.io/component: orchestrator
data:
  ORCHESTRATOR_HOST: "0.0.0.0"
  ORCHESTRATOR_PORT: "8620"
  WORKER_ENDPOINTS: '["http://rpa-worker-service:8621/execute"]'
  MAX_WORKERS: "1"
  WORKER_TIMEOUT: "$WORKER_TIMEOUT"
  JOB_POLL_INTERVAL: "$JOB_POLL_INTERVAL"
  BATCH_SIZE: "1"
  MAX_RETRIES: "3"
  RETRY_DELAY: "30"
  CONCURRENT_JOBS: "1"
  BASE_DATA_DIR: "/app/data"
  DB_PATH: "/app/data/db/orchestrator.db"
  LOG_DIR: "/app/logs"
  EVIDENCE_DIR: "/app/data/evidence"
  SCREENSHOT_DIR: "/app/data/screenshots"
  ADMIN_USERNAME: "admin"
  AUTH_TOKEN_EXPIRE_HOURS: "24"
  ENVIRONMENT: "$ENVIRONMENT_TYPE"
  LOG_LEVEL: "$LOG_LEVEL"
  DEBUG: "false"
  HEADLESS: "true"
  WORKER_COUNT: "$WORKER_REPLICAS"
  ARCHITECTURE: "single_threaded"
  HEALTH_CHECK_INTERVAL: "30"
  METRICS_ENABLED: "true"

---
# ConfigMap for Worker Configuration
apiVersion: v1
kind: ConfigMap
metadata:
  name: worker-config
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-worker
    app.kubernetes.io/component: worker
data:
  WORKER_HOST: "0.0.0.0"
  WORKER_PORT: "8621"
  MAX_WORKERS: "1"
  WORKER_TIMEOUT: "$WORKER_TIMEOUT"
  CONCURRENT_JOBS: "1"
  JOB_QUEUE_SIZE: "5"
  THREAD_POOL_SIZE: "1"
  HEADLESS: "true"
  NO_SANDBOX: "true"
  DISABLE_DEV_SHM_USAGE: "true"
  DISABLE_GPU: "true"
  WINDOW_SIZE: "1920x1080"
  AUTHORIZED_WORKER_IPS: '["10.0.0.0/8","192.168.0.0/16","172.16.0.0/12"]'
  API_TIMEOUT: "30"
  BASE_DATA_DIR: "/app/data"
  LOG_DIR: "/app/logs"
  WORKER_DATA_DIR: "/app/worker_data"
  SCREENSHOT_DIR: "/app/data/screenshots"
  EVIDENCE_DIR: "/app/data/evidence"
  ENVIRONMENT: "$ENVIRONMENT_TYPE"
  LOG_LEVEL: "$LOG_LEVEL"
  DEBUG: "false"
  CHROMEDRIVER_PATH: "/usr/bin/chromedriver"
  CHROME_BINARY_PATH: "/usr/bin/google-chrome"
  SCREENSHOT_ENABLED: "true"
  EVIDENCE_RETENTION_DAYS: "90"
  PERFORMANCE_MONITORING: "true"

---
# Secret for Sensitive Configuration
apiVersion: v1
kind: Secret
metadata:
  name: rpa-secrets
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system
    app.kubernetes.io/component: secrets
type: Opaque
stringData:
  JWT_SECRET: "$jwt_secret"
  ADMIN_PASSWORD: "$admin_password"

---
# PersistentVolumeClaim for Orchestrator Data
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: orchestrator-data
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-orchestrator
    app.kubernetes.io/component: storage
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
EOF

    # Add storage class if detected
    if [[ -n "$SINGLE_STORAGE_CLASS" ]]; then
        echo "  storageClassName: $SINGLE_STORAGE_CLASS" >> "$manifests_file"
    fi

    cat >> "$manifests_file" << EOF

---
# PersistentVolumeClaim for Shared Logs
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: rpa-logs
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system
    app.kubernetes.io/component: logs
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 5Gi
EOF

    # Add storage class if detected
    if [[ -n "$SHARED_STORAGE_CLASS" ]]; then
        echo "  storageClassName: $SHARED_STORAGE_CLASS" >> "$manifests_file"
    fi

    cat >> "$manifests_file" << EOF

---
# Service Account
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rpa-service-account
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system

---
# Security Context Constraint (OpenShift-specific)
apiVersion: security.openshift.io/v1
kind: SecurityContextConstraints
metadata:
  name: rpa-scc-$NAMESPACE
allowHostDirVolumePlugin: false
allowHostIPC: false
allowHostNetwork: false
allowHostPID: false
allowHostPorts: false
allowPrivilegedContainer: false
allowedCapabilities: []
defaultAddCapabilities: []
fsGroup:
  type: MustRunAs
  ranges:
    - min: 1001
      max: 1001
readOnlyRootFilesystem: false
requiredDropCapabilities:
  - ALL
runAsUser:
  type: MustRunAs
  uid: 1001
seLinuxContext:
  type: MustRunAs
supplementalGroups:
  type: MustRunAs
  ranges:
    - min: 1001
      max: 1001
users:
  - system:serviceaccount:$NAMESPACE:rpa-service-account

---
# Orchestrator Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rpa-orchestrator
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-orchestrator
    app.kubernetes.io/component: orchestrator
    app.kubernetes.io/part-of: rpa-system
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app.kubernetes.io/name: rpa-orchestrator
  template:
    metadata:
      labels:
        app.kubernetes.io/name: rpa-orchestrator
        app.kubernetes.io/component: orchestrator
    spec:
      serviceAccountName: rpa-service-account
      securityContext:
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
      containers:
      - name: orchestrator
        image: image-registry.openshift-image-registry.svc:5000/$NAMESPACE/rpa-orchestrator:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8620
          name: api
          protocol: TCP
        envFrom:
        - configMapRef:
            name: orchestrator-config
        - secretRef:
            name: rpa-secrets
        volumeMounts:
        - name: data
          mountPath: /app/data
        - name: logs
          mountPath: /app/logs
        resources:
          requests:
            memory: "$ORCHESTRATOR_MEMORY"
            cpu: "$ORCHESTRATOR_CPU_REQUEST"
          limits:
            memory: "$ORCHESTRATOR_MEMORY"
            cpu: "$ORCHESTRATOR_CPU_LIMIT"
        livenessProbe:
          httpGet:
            path: /health
            port: 8620
          initialDelaySeconds: 60
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8620
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        startupProbe:
          httpGet:
            path: /health
            port: 8620
          initialDelaySeconds: 20
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 12
      volumes:
      - name: data
        persistentVolumeClaim:
          claimName: orchestrator-data
      - name: logs
        persistentVolumeClaim:
          claimName: rpa-logs

---
# Worker Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rpa-worker
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-worker
    app.kubernetes.io/component: worker
    app.kubernetes.io/part-of: rpa-system
spec:
  replicas: $WORKER_REPLICAS
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: rpa-worker
  template:
    metadata:
      labels:
        app.kubernetes.io/name: rpa-worker
        app.kubernetes.io/component: worker
    spec:
      serviceAccountName: rpa-service-account
      securityContext:
        runAsUser: 1001
        runAsGroup: 1001
        fsGroup: 1001
      containers:
      - name: worker
        image: image-registry.openshift-image-registry.svc:5000/$NAMESPACE/rpa-worker:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8621
          name: api
          protocol: TCP
        envFrom:
        - configMapRef:
            name: worker-config
        volumeMounts:
        - name: worker-data
          mountPath: /app/worker_data
        - name: logs
          mountPath: /app/logs
        - name: shared-data
          mountPath: /app/data
        resources:
          requests:
            memory: "$WORKER_MEMORY"
            cpu: "$WORKER_CPU_REQUEST"
          limits:
            memory: "$WORKER_MEMORY"
            cpu: "$WORKER_CPU_LIMIT"
        livenessProbe:
          httpGet:
            path: /health
            port: 8621
          initialDelaySeconds: 60
          periodSeconds: 30
          timeoutSeconds: 10
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /health
            port: 8621
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        startupProbe:
          httpGet:
            path: /health
            port: 8621
          initialDelaySeconds: 20
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 12
      volumes:
      - name: worker-data
        emptyDir:
          sizeLimit: 1Gi
      - name: logs
        persistentVolumeClaim:
          claimName: rpa-logs
      - name: shared-data
        persistentVolumeClaim:
          claimName: orchestrator-data

---
# Orchestrator Service
apiVersion: v1
kind: Service
metadata:
  name: rpa-orchestrator-service
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-orchestrator
    app.kubernetes.io/component: orchestrator
spec:
  type: ClusterIP
  ports:
  - port: 8620
    targetPort: 8620
    protocol: TCP
    name: api
  selector:
    app.kubernetes.io/name: rpa-orchestrator

---
# Worker Service
apiVersion: v1
kind: Service
metadata:
  name: rpa-worker-service
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-worker
    app.kubernetes.io/component: worker
spec:
  type: ClusterIP
  ports:
  - port: 8621
    targetPort: 8621
    protocol: TCP
    name: api
  selector:
    app.kubernetes.io/name: rpa-worker

---
# Orchestrator Route (External Access)
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: rpa-orchestrator-route
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-orchestrator
    app.kubernetes.io/component: orchestrator
spec:
  to:
    kind: Service
    name: rpa-orchestrator-service
  port:
    targetPort: api
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect

---
# Horizontal Pod Autoscaler for Workers
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rpa-worker-hpa
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-worker
    app.kubernetes.io/component: autoscaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rpa-worker
  minReplicas: $HPA_MIN_REPLICAS
  maxReplicas: $HPA_MAX_REPLICAS
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 20
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 50
        periodSeconds: 60

---
# Network Policy for Security
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rpa-network-policy
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system
    app.kubernetes.io/component: security
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: $NAMESPACE
    - namespaceSelector:
        matchLabels:
          network.openshift.io/policy-group: ingress
  - ports:
    - protocol: TCP
      port: 8620
    - protocol: TCP
      port: 8621
  egress:
  - {}

---
# PodDisruptionBudget for Worker Availability
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: rpa-worker-pdb
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-worker
    app.kubernetes.io/component: availability
spec:
  minAvailable: $(( HPA_MIN_REPLICAS > 1 ? HPA_MIN_REPLICAS - 1 : 1 ))
  selector:
    matchLabels:
      app.kubernetes.io/name: rpa-worker

---
# ServiceMonitor for Prometheus (if available)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: rpa-system-monitor
  namespace: $NAMESPACE
  labels:
    app.kubernetes.io/name: rpa-system
    app.kubernetes.io/component: monitoring
spec:
  selector:
    matchLabels:
      app.kubernetes.io/component: orchestrator
  endpoints:
  - port: api
    path: /metrics
    interval: 30s
  - port: api
    path: /health
    interval: 30s
EOF

    EMBEDDED_MANIFESTS_FILE="$manifests_file"
    success "Complete embedded manifests created: $manifests_file"
}

# Deploy manifests to OpenShift
deploy_manifests_to_openshift() {
    section "DEPLOYING COMPLETE RPA SYSTEM TO OPENSHIFT"
    
    if [[ -z "$EMBEDDED_MANIFESTS_FILE" ]]; then
        error "Embedded manifests not created. Run create_embedded_manifests first."
    fi
    
    if [[ ! -f "$EMBEDDED_MANIFESTS_FILE" ]]; then
        error "Manifests file not found: $EMBEDDED_MANIFESTS_FILE"
    fi
    
    if [[ "$DRY_RUN" == true ]]; then
        info "DRY RUN: Would apply the following resources:"
        oc apply -f "$EMBEDDED_MANIFESTS_FILE" --dry-run=client
        return
    fi
    
    # Apply manifests
    info "Applying complete OpenShift manifests..."
    oc apply -f "$EMBEDDED_MANIFESTS_FILE"
    
    # Verify critical resources were created
    info "Verifying resource creation..."
    
    local max_attempts=30
    local attempt=1
    
    # Check namespace
    while [[ $attempt -le $max_attempts ]]; do
        if oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
            break
        fi
        info "Waiting for namespace creation... (attempt $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        error "Namespace creation failed"
    fi
    
    # Apply SCC permissions
    if oc get scc "rpa-scc-$NAMESPACE" >/dev/null 2>&1; then
        oc adm policy add-scc-to-user "rpa-scc-$NAMESPACE" -z rpa-service-account -n "$NAMESPACE" || warning "Could not apply SCC permissions"
    fi
    
    # Check deployments were created
    if ! oc get deployment rpa-orchestrator -n "$NAMESPACE" >/dev/null 2>&1; then
        error "Orchestrator deployment not created"
    fi
    
    if ! oc get deployment rpa-worker -n "$NAMESPACE" >/dev/null 2>&1; then
        error "Worker deployment not created"
    fi
    
    success "Complete manifests deployed successfully"
}

# Wait for deployment completion
wait_for_deployment() {
    if [[ "$DRY_RUN" == true ]]; then
        return
    fi
    
    section "WAITING FOR DEPLOYMENT COMPLETION"
    
    info "Waiting for orchestrator deployment..."
    oc rollout status deployment/rpa-orchestrator -n "$NAMESPACE" --timeout=600s
    
    info "Waiting for worker deployment..."
    oc rollout status deployment/rpa-worker -n "$NAMESPACE" --timeout=600s
    
    # Check pod readiness
    info "Verifying pod readiness..."
    local max_attempts=60
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        local ready_pods=$(oc get pods -l app.kubernetes.io/part-of=rpa-system -n "$NAMESPACE" --no-headers 2>/dev/null | grep "Running" | wc -l || echo "0")
        local total_pods=$(oc get pods -l app.kubernetes.io/part-of=rpa-system -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l || echo "0")
        
        if [[ $ready_pods -eq $total_pods ]] && [[ $total_pods -gt 0 ]]; then
            success "All pods are ready ($ready_pods/$total_pods)"
            break
        fi
        
        info "Waiting for pods to be ready ($ready_pods/$total_pods)... (attempt $attempt/$max_attempts)"
        sleep 10
        ((attempt++))
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        warning "Some pods may not be ready. Check with: oc get pods -n $NAMESPACE"
    fi
    
    success "Deployment completion verified"
}

# Comprehensive system health check
comprehensive_health_check() {
    if [[ "$DRY_RUN" == true ]]; then
        return
    fi
    
    section "COMPREHENSIVE SYSTEM HEALTH CHECK"
    
    # Overall resource status
    info "📊 Resource Overview:"
    oc get all -n "$NAMESPACE" 2>/dev/null | head -20 || warning "Could not retrieve resources"
    
    # Pod status with details
    info "🔍 Pod Details:"
    local pods=($(oc get pods -n "$NAMESPACE" --no-headers -o custom-columns=":metadata.name" 2>/dev/null || echo ""))
    
    if [[ ${#pods[@]} -eq 0 ]]; then
        warning "No pods found in namespace $NAMESPACE"
        return
    fi
    
    for pod in "${pods[@]}"; do
        local status=$(oc get pod "$pod" -n "$NAMESPACE" --no-headers -o custom-columns=":status.phase" 2>/dev/null || echo "Unknown")
        local ready=$(oc get pod "$pod" -n "$NAMESPACE" --no-headers -o custom-columns=":status.containerStatuses[*].ready" 2>/dev/null || echo "false")
        
        if [[ "$status" == "Running" && "$ready" == "true" ]]; then
            info "  ✅ $pod: $status (Ready)"
        else
            warning "  ❌ $pod: $status (Not Ready)"
            
            # Show recent events for problematic pods
            info "     Recent events for $pod:"
            oc get events --field-selector involvedObject.name="$pod" -n "$NAMESPACE" --sort-by='.lastTimestamp' 2>/dev/null | tail -3 || echo "     No events found"
        fi
    done
    
    # Service endpoints
    info "🌐 Service Endpoints:"
    local services=($(oc get svc -n "$NAMESPACE" --no-headers -o custom-columns=":metadata.name" 2>/dev/null || echo ""))
    
    for service in "${services[@]}"; do
        local endpoints=$(oc get endpoints "$service" -n "$NAMESPACE" --no-headers -o custom-columns=":subsets[*].addresses[*].ip" 2>/dev/null | tr ' ' ',' || echo "none")
        if [[ "$endpoints" != "none" && -n "$endpoints" ]]; then
            info "  ✅ $service: $endpoints"
        else
            warning "  ❌ $service: No endpoints"
        fi
    done
    
    # Route accessibility
    info "🔗 External Access:"
    if oc get route rpa-orchestrator-route -n "$NAMESPACE" >/dev/null 2>&1; then
        local route_host=$(oc get route rpa-orchestrator-route -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "unknown")
        local route_tls=$(oc get route rpa-orchestrator-route -n "$NAMESPACE" -o jsonpath='{.spec.tls.termination}' 2>/dev/null || echo "none")
        
        if [[ "$route_tls" == "edge" ]]; then
            info "  🔒 HTTPS: https://$route_host"
        else
            info "  🌐 HTTP: http://$route_host"
        fi
    fi
    
    # Auto-scaling status
    info "📈 Auto-scaling Status:"
    if oc get hpa rpa-worker-hpa -n "$NAMESPACE" >/dev/null 2>&1; then
        local current_replicas=$(oc get hpa rpa-worker-hpa -n "$NAMESPACE" -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "0")
        local desired_replicas=$(oc get hpa rpa-worker-hpa -n "$NAMESPACE" -o jsonpath='{.status.desiredReplicas}' 2>/dev/null || echo "0")
        local min_replicas=$(oc get hpa rpa-worker-hpa -n "$NAMESPACE" -o jsonpath='{.spec.minReplicas}' 2>/dev/null || echo "0")
        local max_replicas=$(oc get hpa rpa-worker-hpa -n "$NAMESPACE" -o jsonpath='{.spec.maxReplicas}' 2>/dev/null || echo "0")
        
        info "  📊 Workers: $current_replicas/$desired_replicas (range: $min_replicas-$max_replicas)"
    fi
    
    # Storage status
    info "💾 Storage Status:"
    oc get pvc -n "$NAMESPACE" 2>/dev/null | grep -E "(NAME|rpa-)" || warning "No PVCs found"
    
    # Image streams
    info "📦 Container Images:"
    oc get imagestream -n "$NAMESPACE" 2>/dev/null | grep -E "(NAME|rpa-)" || warning "No image streams found"
    
    success "Comprehensive health check completed"
}

# Display complete system information
display_complete_system_info() {
    section "COMPLETE RPA SYSTEM INSTALLATION SUMMARY"
    
    if [[ "$DRY_RUN" == true ]]; then
        info "DRY RUN COMPLETED - No resources were actually created"
        info "This fresh installation would have created a complete RPA system"
        return
    fi
    
    # Get route URL
    local orchestrator_url=""
    if oc get route rpa-orchestrator-route -n "$NAMESPACE" >/dev/null 2>&1; then
        orchestrator_url="https://$(oc get route rpa-orchestrator-route -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
    fi
    
    # Get admin password
    local admin_password=""
    if [[ -f "$HOME/.rpa-admin-password" ]]; then
        admin_password=$(cat "$HOME/.rpa-admin-password")
    fi
    
    # Get current pod count
    local current_workers=$(oc get pods -l app.kubernetes.io/name=rpa-worker -n "$NAMESPACE" --no-headers 2>/dev/null | grep "Running" | wc -l || echo "0")
    local orchestrator_status=$(oc get pods -l app.kubernetes.io/name=rpa-orchestrator -n "$NAMESPACE" --no-headers 2>/dev/null | grep "Running" | wc -l || echo "0")
    
    echo -e "${CYAN}🎉 Complete OpenShift RPA Fresh Installation SUCCESS! 🎉${NC}"
    echo
    echo -e "${CYAN}📋 Installation Summary:${NC}"
    echo -e "  🏠 Namespace: ${YELLOW}$NAMESPACE${NC}"
    echo -e "  🎯 Environment: ${YELLOW}$ENVIRONMENT_TYPE${NC}"
    echo -e "  📁 Source Directory: ${YELLOW}$SOURCE_DIR${NC}"
    echo -e "  🏗️  Architecture: ${YELLOW}Kubernetes-native RPA System${NC}"
    echo -e "  👥 Current Workers: ${YELLOW}$current_workers running${NC}"
    echo -e "  🎛️  Orchestrator: ${YELLOW}$orchestrator_status running${NC}"
    echo -e "  📈 Auto-scaling: ${YELLOW}$HPA_MIN_REPLICAS-$HPA_MAX_REPLICAS workers${NC}"
    echo -e "  💾 Worker Memory: ${YELLOW}$WORKER_MEMORY each${NC}"
    echo -e "  💾 Orchestrator Memory: ${YELLOW}$ORCHESTRATOR_MEMORY${NC}"
    echo -e "  🔑 Admin Password: ${YELLOW}$admin_password${NC}"
    
    if [[ -n "$orchestrator_url" ]]; then
        echo -e "\n${CYAN}🌐 Access Points:${NC}"
        echo -e "  🎛️  Orchestrator UI: ${YELLOW}$orchestrator_url${NC}"
        echo -e "  📊 Admin Username: ${YELLOW}admin${NC}"
        echo -e "  🔐 Admin Password: ${YELLOW}$admin_password${NC}"
    fi
    
    echo -e "\n${CYAN}🚀 Fresh Installation Features:${NC}"
    echo -e "  ✅ Complete source code deployment from: ${YELLOW}$SOURCE_DIR${NC}"
    echo -e "  ✅ Auto-detected storage classes: ${YELLOW}$SINGLE_STORAGE_CLASS, $SHARED_STORAGE_CLASS${NC}"
    echo -e "  ✅ Environment-optimized configurations for ${YELLOW}$ENVIRONMENT_TYPE${NC}"
    echo -e "  ✅ Built container images with embedded Containerfiles"
    echo -e "  ✅ Persistent storage for data and logs"
    echo -e "  ✅ Automatic SSL/TLS termination"
    echo -e "  ✅ Auto-scaling based on CPU and memory usage"
    echo -e "  ✅ Network policies and security contexts"
    echo -e "  ✅ Health checks and monitoring probes"
    echo -e "  ✅ Complete embedded manifests (no external dependencies)"
    
    echo -e "\n${CYAN}🔧 Management Commands:${NC}"
    echo -e "  ${BLUE}oc get all -n $NAMESPACE${NC}                    - View all resources"
    echo -e "  ${BLUE}oc get pods -n $NAMESPACE${NC}                   - Check pod status"
    echo -e "  ${BLUE}oc logs deployment/rpa-orchestrator -n $NAMESPACE -f${NC} - View orchestrator logs"
    echo -e "  ${BLUE}oc logs -l app.kubernetes.io/name=rpa-worker -n $NAMESPACE -f${NC} - View worker logs"
    echo -e "  ${BLUE}oc scale deployment rpa-worker --replicas=8 -n $NAMESPACE${NC} - Scale workers manually"
    echo -e "  ${BLUE}oc get hpa -n $NAMESPACE${NC}                    - Check auto-scaling status"
    echo -e "  ${BLUE}oc get route -n $NAMESPACE${NC}                  - Get external URLs"
    
    echo -e "\n${CYAN}📊 Resource Usage:${NC}"
    if command -v oc >/dev/null 2>&1; then
        echo -e "  💾 Storage Claims:"
        oc get pvc -n "$NAMESPACE" 2>/dev/null | head -10 || echo "    Unable to retrieve PVC status"
        
        echo -e "  🔄 Auto-scaling Status:"
        oc get hpa -n "$NAMESPACE" 2>/dev/null | head -5 || echo "    Unable to retrieve HPA status"
    fi
    
    echo -e "\n${CYAN}🛠️  Next Steps:${NC}"
    echo -e "  1. Verify all pods are running: ${BLUE}oc get pods -n $NAMESPACE${NC}"
    echo -e "  2. Test orchestrator UI: ${YELLOW}$orchestrator_url${NC}"
    echo -e "  3. Submit a test automation job"
    echo -e "  4. Monitor auto-scaling behavior under load"
    echo -e "  5. Set up monitoring and alerting (if available)"
    
    echo -e "\n${CYAN}🔐 Important Files Created:${NC}"
    if [[ -f "$HOME/.rpa-admin-password" ]]; then
        echo -e "  🔑 Admin password: ${YELLOW}$HOME/.rpa-admin-password${NC}"
    fi
    
    if [[ -n "$EMBEDDED_MANIFESTS_FILE" ]]; then
        local final_manifests="$HOME/rpa-openshift-manifests-$(date +%Y%m%d-%H%M%S).yaml"
        cp "$EMBEDDED_MANIFESTS_FILE" "$final_manifests" 2>/dev/null && \
        echo -e "  📄 Deployment manifests: ${YELLOW}$final_manifests${NC}"
    fi
    
    echo -e "\n${CYAN}⚠️  Key Differences from Podman Deployment:${NC}"
    echo -e "  🔄 Service discovery: ${YELLOW}rpa-worker-service:8621${NC} (not fixed IPs)"
    echo -e "  🌐 Networking: ${YELLOW}Kubernetes Services + Routes${NC} (not host ports)"
    echo -e "  📦 Storage: ${YELLOW}PersistentVolumeClaims${NC} (not bind mounts)"
    echo -e "  🔄 Scaling: ${YELLOW}Dynamic auto-scaling${NC} (not fixed 5 workers)"
    echo -e "  🔒 Security: ${YELLOW}OpenShift security contexts${NC} (not host-based)"
    echo -e "  📈 Monitoring: ${YELLOW}Built-in Kubernetes probes${NC} (not custom scripts)"
    
    echo -e "\n${GREEN}✅ Your complete RPA system is now running on OpenShift!${NC}"
    echo -e "${YELLOW}🚀 This fresh installation includes everything from your original deployment script!${NC}"
}

# Cleanup function
cleanup() {
    if [[ -f "/tmp/rpa-manifests-${NAMESPACE}-$$.yaml" ]]; then
        rm -f "/tmp/rpa-manifests-${NAMESPACE}-$$.yaml"
    fi
    
    if [[ -n "$BUILD_DIR" && -d "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"
    fi
}

# Main execution function
main() {
    trap cleanup EXIT
    
    echo -e "${CYAN}"
    cat << 'EOF'
    ╔════════════════════════════════════════════════════════════════════╗
    ║           Complete Self-Contained OpenShift RPA Installer         ║
    ║                                                                    ║
    ║           🚀 5-Worker + 1-Orchestrator Architecture 🚀            ║
    ║                                                                    ║
    ║    Fresh RHEL server installation with embedded components        ║
    ║    • All Containerfiles embedded                                  ║
    ║    • All manifests embedded                                       ║
    ║    • No discovery directory required                              ║
    ║    • Complete replacement for rpa-production-deployment.sh        ║
    ╚════════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
    
    parse_arguments "$@"
    check_prerequisites
    
    # Create namespace if it doesn't exist
    if [[ "$DRY_RUN" == false ]]; then
        oc new-project "$PROJECT_NAME" 2>/dev/null || oc project "$PROJECT_NAME"
    fi
    
    # Complete fresh installation pipeline
    detect_storage_classes
    generate_environment_configs
    prepare_build_directory
    create_embedded_containerfiles
    build_images_in_openshift
    create_embedded_manifests
    deploy_manifests_to_openshift
    wait_for_deployment
    comprehensive_health_check
    display_complete_system_info
    
    success "🎉 Complete OpenShift RPA fresh installation completed successfully!"
    
    # Clean up build directory but keep manifests for reference
    if [[ -n "$BUILD_DIR" && -d "$BUILD_DIR" ]]; then
        rm -rf "$BUILD_DIR"
        info "🧹 Cleaned up temporary build directory"
    fi
    
    if [[ -n "$EMBEDDED_MANIFESTS_FILE" && -f "$EMBEDDED_MANIFESTS_FILE" ]]; then
        local final_manifests="$HOME/rpa-openshift-manifests-$(date +%Y%m%d-%H%M%S).yaml"
        cp "$EMBEDDED_MANIFESTS_FILE" "$final_manifests" 2>/dev/null && \
        info "📄 Complete manifests saved to: $final_manifests"
    fi
}

# Execute main function
main "$@"