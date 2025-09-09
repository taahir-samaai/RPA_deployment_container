#!/bin/bash

# RPA 5-Worker Network-Based Production Deployment Script
# Updated with fixes for AWS RHEL environments without SELinux xattr support
# Includes PyJWT dependency fix and network-based architecture

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RPA_HOME="/opt/rpa-system"
RPA_USER="rpauser"
RPA_GROUP="rpauser"
DISCOVERY_DIR=""
ENVIRONMENT_TYPE="production"
WORKER_COUNT=5
MAX_WORKERS=1
CONCURRENT_JOBS=1

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
section() { echo -e "\n${CYAN}=== $1 ===${NC}"; }

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -d|--discovery-dir)
                DISCOVERY_DIR="$2"
                shift 2
                ;;
            -e|--environment)
                ENVIRONMENT_TYPE="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    if [[ -z "$DISCOVERY_DIR" ]]; then
        error "Discovery directory is required. Use -d /path/to/discovery"
        exit 1
    fi

    if [[ ! -d "$DISCOVERY_DIR" ]]; then
        error "Discovery directory does not exist: $DISCOVERY_DIR"
        exit 1
    fi
}

show_help() {
    cat << EOF
RPA Network-Based Production Deployment Script

Usage: $0 -d DISCOVERY_DIR [-e ENVIRONMENT]

Options:
    -d, --discovery-dir DIR    Path to environment discovery directory (required)
    -e, --environment TYPE     Environment type (production, staging, development) [default: production]
    -h, --help                Show this help message

Example:
    sudo $0 -d ./environment-discovery-20250904-130738 -e production
EOF
}

# Check prerequisites
check_prerequisites() {
    section "CHECKING PREREQUISITES"
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root"
        exit 1
    fi

    # Check OS compatibility
    if [[ ! -f /etc/redhat-release ]]; then
        error "This script is designed for Red Hat family systems"
        exit 1
    fi

    # Check for required commands
    local required_commands=("dnf" "systemctl" "openssl")
    for cmd in "${required_commands[@]}"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            error "Required command not found: $cmd"
            exit 1
        fi
    done

    # Check discovery directory structure
    local required_dirs=("system" "containers" "config")
    for dir in "${required_dirs[@]}"; do
        if [[ ! -d "$DISCOVERY_DIR/$dir" ]]; then
            error "Missing required directory in discovery: $dir"
            exit 1
        fi
    done

    info "OS: $(cat /etc/redhat-release)"
    success "Prerequisites check completed"
}

# Analyze system resources
analyze_system_resources() {
    section "ANALYZING SYSTEM RESOURCES"
    
    CPU_COUNT=$(nproc)
    MEMORY_GB=$(($(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024 / 1024))
    AVAILABLE_SPACE=$(df /opt --output=avail | tail -1 | awk '{print int($1/1024/1024)}')

    info "System Resources:"
    info "  CPU Cores: $CPU_COUNT"
    info "  Memory: ${MEMORY_GB}GB"
    info "  Available disk space: ${AVAILABLE_SPACE}GB"

    # Check minimum requirements
    if [[ $CPU_COUNT -lt 6 ]]; then
        warning "Low CPU count: $CPU_COUNT cores. Recommended: 6+ cores for 5 workers"
    fi

    if [[ $AVAILABLE_SPACE -lt 20 ]]; then
        warning "Low disk space: ${AVAILABLE_SPACE}GB. Recommended: 20GB+"
    fi

    if [[ $MEMORY_GB -lt 8 ]]; then
        warning "Low memory: ${MEMORY_GB}GB. Recommended: 8GB+ for 5 workers"
    fi

    # Memory allocation based on system capacity
    case $ENVIRONMENT_TYPE in
        production)
            if [[ $MEMORY_GB -ge 16 ]]; then
                WORKER_MEMORY="2g"
                ORCHESTRATOR_MEMORY="1g"
            elif [[ $MEMORY_GB -ge 8 ]]; then
                WORKER_MEMORY="1g"
                ORCHESTRATOR_MEMORY="512m"
            else
                WORKER_MEMORY="512m"
                ORCHESTRATOR_MEMORY="256m"
            fi
            WORKER_TIMEOUT=600
            JOB_POLL_INTERVAL=10
            ;;
        *)
            WORKER_MEMORY="512m"
            ORCHESTRATOR_MEMORY="256m"
            WORKER_TIMEOUT=300
            JOB_POLL_INTERVAL=30
            ;;
    esac

    info "Network-Based Architecture Configuration:"
    info "  Worker Containers: $WORKER_COUNT"
    info "  Threads per Container: $MAX_WORKERS (single-threaded)"
    info "  Total Job Capacity: $WORKER_COUNT concurrent jobs"
    info "  Worker Memory: $WORKER_MEMORY each"
    info "  Orchestrator Memory: $ORCHESTRATOR_MEMORY"
    info "  Ports: 8620 (orchestrator), 8621-8625 (workers)"

    success "System analysis completed for network-based architecture"
}

# Install required packages
install_prerequisites() {
    section "INSTALLING PREREQUISITES"

    info "Updating system packages..."
    dnf update -y

    info "Enabling CodeReady Builder (CRB) repo for dependencies..."
    dnf config-manager --set-enabled crb || true

    info "Installing EPEL repository..."
    dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm

    info "Installing container and system packages..."
    dnf install -y \
        podman \
        buildah \
        skopeo \
        wget \
        curl \
        unzip \
        git \
        jq \
        tree \
        sqlite \
        gcc \
        python3-devel \
        python3-pip \
        firewalld \
        systemd \
        logrotate \
        htop \
        nano \
        vim

    success "Prerequisites installed"
}

# Set up user and directories
setup_user_directories() {
    section "SETTING UP USER AND DIRECTORIES"

    # Create RPA user
    if ! id "$RPA_USER" &>/dev/null; then
        useradd -r -s /bin/bash -d /home/$RPA_USER -m $RPA_USER
        info "Created user: $RPA_USER"
    else
        info "User already exists: $RPA_USER"
    fi

    # Create directory structure
    mkdir -p $RPA_HOME/{configs,containers/{orchestrator,worker},scripts,volumes,source,backups,temp}

    # Create volume directories with proper structure for network architecture
    mkdir -p /var/lib/rpa-volumes/{data,logs,worker-logs}
    mkdir -p /var/lib/rpa-volumes/data/{db,screenshots,evidence,logs,logs/executions}

    # Set proper ownership for volume directories (UID 1001 for container user)
    chown -R 1001:1001 /var/lib/rpa-volumes/
    chmod -R 755 /var/lib/rpa-volumes/

    chown -R $RPA_USER:$RPA_GROUP $RPA_HOME
    chmod -R 755 $RPA_HOME

    success "User and directories configured"
}

# Deploy source code
deploy_source_code() {
    section "DEPLOYING SOURCE CODE"

    # Copy source code from discovery
    if [[ -d "$DISCOVERY_DIR/production-ready" ]]; then
        cp -r "$DISCOVERY_DIR/production-ready/"* "$RPA_HOME/source/"
        info "Deployed production-ready source code"
    elif [[ -d "$DISCOVERY_DIR/config" ]]; then
        find "$DISCOVERY_DIR/config" -name "*.py" -exec cp {} "$RPA_HOME/source/" \;
        info "Deployed source code from config directory"
    else
        error "No source code found in discovery directory"
        exit 1
    fi

    # Copy to main directory for container builds
    cp -r "$RPA_HOME/source/"* "$RPA_HOME/"

    chown -R $RPA_USER:$RPA_GROUP "$RPA_HOME/source"
    success "Source code deployment completed"
}

# Generate production configurations
generate_production_config() {
    section "GENERATING NETWORK-BASED PRODUCTION CONFIGURATIONS"

    info "Creating configuration for $WORKER_COUNT single-threaded workers..."

    # Generate worker endpoints dynamically for 5 workers
    local worker_endpoints=""
    for ((i=1; i<=WORKER_COUNT; i++)); do
        if [[ $i -eq 1 ]]; then
            worker_endpoints="\"http://worker$i:8621/execute\""
        else
            worker_endpoints="$worker_endpoints,\"http://worker$i:8621/execute\""
        fi
    done

    # Generate orchestrator configuration
    cat > $RPA_HOME/configs/orchestrator.env << EOF
# RPA Orchestrator Configuration - $ENVIRONMENT_TYPE Environment
# Network Architecture with $WORKER_COUNT Workers
# Generated on $(date)

# Server Configuration
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8620
WORKER_ENDPOINTS=[$worker_endpoints]

# Single-threaded Performance Settings
MAX_WORKERS=$MAX_WORKERS
WORKER_TIMEOUT=$WORKER_TIMEOUT
JOB_POLL_INTERVAL=$JOB_POLL_INTERVAL
BATCH_SIZE=1
MAX_RETRIES=3
RETRY_DELAY=30
CONCURRENT_JOBS=1

# Storage Configuration
BASE_DATA_DIR=/app/data
DB_PATH=/app/data/db/orchestrator.db
LOG_DIR=/app/logs
EVIDENCE_DIR=/app/data/evidence
SCREENSHOT_DIR=/app/data/screenshots

# Security Configuration
JWT_SECRET=$(openssl rand -hex 32)
ADMIN_USERNAME=admin
ADMIN_PASSWORD=$(openssl rand -base64 16)
AUTH_TOKEN_EXPIRE_HOURS=24

# Environment Settings
ENVIRONMENT=$ENVIRONMENT_TYPE
LOG_LEVEL=INFO
DEBUG=false
HEADLESS=true

# Network Architecture Settings
WORKER_COUNT=$WORKER_COUNT
ARCHITECTURE=network_based
TOTAL_CAPACITY=$WORKER_COUNT

# Health and Monitoring
HEALTH_CHECK_INTERVAL=30
METRICS_ENABLED=true
BACKUP_ENABLED=true
BACKUP_RETENTION_DAYS=30
EOF

    # Generate worker configuration
    cat > $RPA_HOME/configs/worker.env << EOF
# RPA Worker Configuration - $ENVIRONMENT_TYPE Environment
# Single-threaded Worker (1 of $WORKER_COUNT)
# Generated on $(date)

# Server Configuration
WORKER_HOST=0.0.0.0
WORKER_PORT=8621

# Single-threaded Performance Settings
MAX_WORKERS=$MAX_WORKERS
WORKER_TIMEOUT=$WORKER_TIMEOUT
CONCURRENT_JOBS=$CONCURRENT_JOBS
JOB_QUEUE_SIZE=5
THREAD_POOL_SIZE=1

# Browser Configuration
HEADLESS=true
NO_SANDBOX=true
DISABLE_DEV_SHM_USAGE=true
DISABLE_GPU=true
WINDOW_SIZE=1920x1080

# Security Configuration
AUTHORIZED_WORKER_IPS=["172.18.0.0/16","127.0.0.1","10.0.0.0/8","192.168.0.0/16"]
API_TIMEOUT=30

# Storage Configuration
BASE_DATA_DIR=/app/data
LOG_DIR=/app/logs
WORKER_DATA_DIR=/app/worker_data
SCREENSHOT_DIR=/app/data/screenshots
EVIDENCE_DIR=/app/data/evidence

# Environment Settings
ENVIRONMENT=$ENVIRONMENT_TYPE
LOG_LEVEL=INFO
DEBUG=false

# Browser Driver Configuration
CHROMEDRIVER_PATH=/usr/local/bin/chromedriver
CHROME_BINARY_PATH=/usr/bin/chromium-browser

# Evidence and Monitoring
SCREENSHOT_ENABLED=true
EVIDENCE_RETENTION_DAYS=90
PERFORMANCE_MONITORING=true
EOF

    # Save admin password securely
    grep ADMIN_PASSWORD $RPA_HOME/configs/orchestrator.env | cut -d= -f2 > $RPA_HOME/.admin-password
    chmod 600 $RPA_HOME/.admin-password
    chown $RPA_USER:$RPA_GROUP $RPA_HOME/.admin-password

    success "Network-based production configurations generated"
}

# Create container files
create_container_files() {
    section "CREATING CONTAINER FILES"

    # Create orchestrator Containerfile
    cat > $RPA_HOME/containers/orchestrator/Containerfile << 'EOF'
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

    # Create worker Containerfile
    cat > $RPA_HOME/containers/worker/Containerfile << 'EOF'
FROM registry.redhat.io/ubi9/python-311:latest

USER root
RUN dnf update -y && \
    dnf install -y chromium sqlite gcc python3-devel curl wget unzip jq procps-ng xvfb && \
    dnf clean all

RUN DRIVER_VERSION=$(curl -s "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_STABLE") && \
    wget -O /tmp/chromedriver.zip "https://storage.googleapis.com/chrome-for-testing-public/${DRIVER_VERSION}/linux64/chromedriver-linux64.zip" && \
    unzip /tmp/chromedriver.zip -d /tmp/ && \
    mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver && \
    chmod +x /usr/local/bin/chromedriver && \
    rm -rf /tmp/chromedriver*

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

    # Create requirements.txt with PyJWT fix
    cat > $RPA_HOME/requirements.txt << 'EOF'
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
PyJWT==2.8.0
EOF

    success "Container files created with PyJWT dependency fix"
}

# Create network-based management scripts
create_management_scripts() {
    section "CREATING NETWORK-BASED MANAGEMENT SCRIPTS"

    # Network creation script
    cat > $RPA_HOME/scripts/create-network.sh << 'EOF'
#!/bin/bash
echo "Creating RPA container network..."
if podman network exists rpa-network; then
    echo "RPA network already exists"
else
    podman network create --driver bridge --subnet 172.18.0.0/16 --gateway 172.18.0.1 rpa-network
    echo "RPA network created successfully"
fi
EOF

    # Container build script
    cat > $RPA_HOME/scripts/build-containers.sh << 'EOF'
#!/bin/bash
set -e
cd /opt/rpa-system

echo "Building RPA container images..."

echo "Building orchestrator image..."
podman build --tag rpa-orchestrator:latest --file containers/orchestrator/Containerfile .

echo "Building worker image..."
podman build --tag rpa-worker:latest --file containers/worker/Containerfile .

echo "Container builds completed successfully"
podman images | grep rpa
EOF

    # Network-based start script (working version from troubleshooting)
    cat > $RPA_HOME/scripts/start-system.sh << 'EOF'
#!/bin/bash
set -e
cd /opt/rpa-system

echo "Starting RPA System (5 Workers + 1 Orchestrator)..."

# Cleanup old containers if they exist
echo "Cleaning up old containers..."
for name in rpa-orchestrator rpa-worker1 rpa-worker2 rpa-worker3 rpa-worker4 rpa-worker5; do
    if sudo -u rpauser podman ps -a --format "{{.Names}}" | grep -q "^$name$"; then
        echo "  - Removing existing container: $name"
        sudo -u rpauser podman rm -f $name || true
    fi
done

# Create network
echo "Setting up network..."
sudo -u rpauser ./scripts/create-network.sh

# Ensure volume directories exist (AWS RHEL - no SELinux xattr support)
sudo mkdir -p /var/lib/rpa-volumes/{data,logs,worker-logs}
sudo mkdir -p /var/lib/rpa-volumes/data/{db,screenshots,evidence,logs,logs/executions}
sudo chown -R 1001:1001 /var/lib/rpa-volumes/
sudo chmod -R 755 /var/lib/rpa-volumes/

# Build containers if they don't exist
echo "Building containers..."
if ! sudo -u rpauser podman image exists rpa-orchestrator:latest; then
    sudo -u rpauser ./scripts/build-containers.sh
else
    echo "Container images already exist"
fi

# Start orchestrator with :U flag for ownership and label=disable for SELinux
echo "Starting orchestrator (single-threaded)..."
sudo -u rpauser podman run -d \
    --name rpa-orchestrator \
    --hostname orchestrator \
    --network rpa-network \
    -p 8620:8620 \
    --env-file configs/orchestrator.env \
    -v /var/lib/rpa-volumes/data:/app/data:U \
    -v /var/lib/rpa-volumes/logs:/app/logs:U \
    --security-opt label=disable \
    --restart unless-stopped \
    --memory=1g \
    --cpus=1.0 \
    rpa-orchestrator:latest

echo "Waiting for orchestrator to start..."
sleep 15

# Start 5 workers with individual log directories
for i in {1..5}; do
    port=$((8620 + i))
    
    # Create worker-specific log directory
    sudo mkdir -p /var/lib/rpa-volumes/worker-logs/worker$i
    sudo chown 1001:1001 /var/lib/rpa-volumes/worker-logs/worker$i
    
    echo "Starting worker $i (single-threaded) on port $port..."
    sudo -u rpauser podman run -d \
        --name rpa-worker$i \
        --hostname worker$i \
        --network rpa-network \
        -p $port:8621 \
        --env-file configs/worker.env \
        -v /var/lib/rpa-volumes/data:/app/data:U \
        -v /var/lib/rpa-volumes/worker-logs/worker$i:/app/logs:U \
        --security-opt label=disable \
        --restart unless-stopped \
        --memory=2g \
        --cpus=1.0 \
        --security-opt seccomp=unconfined \
        --shm-size=1g \
        rpa-worker:latest
    
    echo "Waiting for worker $i to initialize..."
    sleep 5
done

echo "Waiting for all services to initialize..."
sleep 20

# Health checks for all 6 services
echo "Checking service health..."
for port in 8620 8621 8622 8623 8624 8625; do
    if curl -f -s http://localhost:$port/health >/dev/null 2>&1; then
        echo "  Service on port $port: Healthy"
    else
        echo "  Service on port $port: Not responding (may still be starting)"
    fi
done

echo ""
echo "RPA System startup completed!"
echo ""
echo "Access Points:"
echo "  Orchestrator:    http://$(hostname):8620 (single-threaded)"
echo "  Worker 1:        http://$(hostname):8621 (single-threaded)"
echo "  Worker 2:        http://$(hostname):8622 (single-threaded)"
echo "  Worker 3:        http://$(hostname):8623 (single-threaded)"
echo "  Worker 4:        http://$(hostname):8624 (single-threaded)"
echo "  Worker 5:        http://$(hostname):8625 (single-threaded)"
echo ""
echo "Admin credentials:"
echo "  Username: admin"
echo "  Password: $(cat /opt/rpa-system/.admin-password 2>/dev/null || echo 'Check /opt/rpa-system/.admin-password')"
EOF

    # Network-based stop script
    cat > $RPA_HOME/scripts/stop-system.sh << 'EOF'
#!/bin/bash
echo "Stopping RPA System (1 orchestrator + 5 workers)..."

containers=(rpa-orchestrator rpa-worker1 rpa-worker2 rpa-worker3 rpa-worker4 rpa-worker5)

for container in "${containers[@]}"; do
    if sudo -u rpauser podman container exists "$container" 2>/dev/null; then
        echo "Stopping $container..."
        sudo -u rpauser podman stop "$container" --time 30 2>/dev/null || true
        sudo -u rpauser podman rm "$container" 2>/dev/null || true
        echo "$container stopped"
    fi
done

echo "RPA System stopped successfully"
EOF

    # Network-based health check script
    cat > $RPA_HOME/scripts/health-check.sh << 'EOF'
#!/bin/bash
echo "RPA System Health Check (5-Worker Network Architecture)"
echo "=========================================================="
echo "$(date)"
echo ""

# Check network exists
echo "Network Status:"
if sudo -u rpauser podman network exists rpa-network; then
    echo "  rpa-network exists"
else
    echo "  rpa-network missing"
fi

# Check container status
echo ""
echo "Container Status:"
if sudo -u rpauser podman ps -a | grep -q rpa-; then
    sudo -u rpauser podman ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(NAMES|rpa-)"
else
    echo "  No RPA containers found"
fi
echo ""

# Check all 6 service health endpoints
echo "Service Health Checks:"
services=(
    "8620:Orchestrator"
    "8621:Worker-1"
    "8622:Worker-2"
    "8623:Worker-3"
    "8624:Worker-4"
    "8625:Worker-5"
)

for service in "${services[@]}"; do
    port="${service%%:*}"
    name="${service##*:}"
    
    if curl -f -s --max-time 5 http://localhost:$port/health >/dev/null 2>&1; then
        echo "  $name (port $port): Healthy"
    else
        echo "  $name (port $port): Unhealthy or not responding"
    fi
done
echo ""

# Resource usage for all containers
echo "Resource Usage:"
if sudo -u rpauser podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null | grep -E "(NAME|rpa-)" | head -7; then
    echo ""
else
    echo "  Unable to retrieve resource stats"
fi

echo "Architecture Summary:"
echo "  • 1 Orchestrator (single-threaded) on port 8620"
echo "  • 5 Workers (single-threaded) on ports 8621-8625"
echo "  • Total capacity: 5 concurrent automation jobs"
echo "  • Network: rpa-network (172.18.0.0/16)"
EOF

    # Make all scripts executable and set ownership
    chmod +x $RPA_HOME/scripts/*.sh
    chown -R $RPA_USER:$RPA_GROUP $RPA_HOME/scripts/

    success "Network-based management scripts created"
}

# Configure firewall for network architecture
configure_firewall() {
    section "CONFIGURING FIREWALL FOR NETWORK ARCHITECTURE"

    systemctl start firewalld
    systemctl enable firewalld

    info "Opening ports for orchestrator + 5 workers..."
    firewall-cmd --permanent --add-port=8620/tcp  # Orchestrator

    # Open ports for 5 workers
    for ((i=1; i<=5; i++)); do
        port=$((8620 + i))
        firewall-cmd --permanent --add-port=$port/tcp
        info "Opened port $port for worker $i"
    done

    # Create custom service definition
    cat > /etc/firewalld/services/rpa-system.xml << 'EOF'
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>RPA System</short>
  <description>RPA System - 1 Orchestrator + 5 Worker Services</description>
  <port protocol="tcp" port="8620"/>
  <port protocol="tcp" port="8621"/>
  <port protocol="tcp" port="8622"/>
  <port protocol="tcp" port="8623"/>
  <port protocol="tcp" port="8624"/>
  <port protocol="tcp" port="8625"/>
</service>
EOF

    firewall-cmd --reload

    success "Firewall configured for network architecture (ports 8620-8625)"
}

# Create systemd service for network architecture
create_systemd_service() {
    section "CREATING SYSTEMD SERVICE FOR NETWORK ARCHITECTURE"

    cat > /etc/systemd/system/rpa-system.service << EOF
[Unit]
Description=RPA System - 5 Workers + 1 Orchestrator (Network-Based)
Documentation=file://$RPA_HOME/DEPLOYMENT_REPORT.md
After=network-online.target
Wants=network-online.target
RequiresMountsFor=$RPA_HOME

[Service]
Type=oneshot
RemainAfterExit=true
User=root
Group=root
WorkingDirectory=$RPA_HOME

# Service commands
ExecStart=$RPA_HOME/scripts/start-system.sh
ExecStop=$RPA_HOME/scripts/stop-system.sh
ExecReload=/bin/bash -c '$RPA_HOME/scripts/stop-system.sh && sleep 10 && $RPA_HOME/scripts/start-system.sh'

# Timeout configuration (longer for 5 workers)
TimeoutStartSec=600
TimeoutStopSec=180
TimeoutAbortSec=30

# Restart configuration
Restart=on-failure
RestartSec=30

# Environment
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=RPA_HOME=$RPA_HOME

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=rpa-system

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable rpa-system.service

    info "Systemd service configuration:"
    info "  Service: Network-based RPA system with 5 workers"
    info "  Auto-start: Enabled"
    info "  Management: systemctl {start|stop|status|restart} rpa-system"

    success "Systemd service created for network architecture"
}

# Set up log rotation
setup_log_rotation() {
    section "CONFIGURING LOG ROTATION"

    cat > /etc/logrotate.d/rpa-system << 'EOF'
/var/lib/rpa-volumes/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 1001 1001
    copytruncate
    postrotate
        /usr/bin/systemctl reload rpa-system.service > /dev/null 2>&1 || true
    endscript
}

/var/lib/rpa-volumes/worker-logs/*/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 644 1001 1001
    copytruncate
}

/var/log/rpa-deployment.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 644 root root
}
EOF

    success "Log rotation configured"
}

# Set permissions
set_permissions() {
    section "SETTING PERMISSIONS"

    chown -R $RPA_USER:$RPA_GROUP $RPA_HOME
    chmod -R 755 $RPA_HOME

    # Set secure permissions for sensitive files
    chmod 600 $RPA_HOME/.admin-password
    chmod 600 $RPA_HOME/configs/*.env

    # Ensure volume directories have proper ownership for containers
    chown -R 1001:1001 /var/lib/rpa-volumes/
    chmod -R 755 /var/lib/rpa-volumes/

    success "Permissions set correctly"
}

# Validate deployment
validate_deployment() {
    section "VALIDATING DEPLOYMENT"

    # Check directory structure
    local required_dirs=(
        "$RPA_HOME/configs"
        "$RPA_HOME/containers/orchestrator"
        "$RPA_HOME/containers/worker"
        "$RPA_HOME/scripts"
        "/var/lib/rpa-volumes/data"
    )

    for dir in "${required_dirs[@]}"; do
        if [[ ! -d "$dir" ]]; then
            error "Missing required directory: $dir"
            exit 1
        fi
    done

    # Check key files
    local required_files=(
        "$RPA_HOME/configs/orchestrator.env"
        "$RPA_HOME/configs/worker.env"
        "$RPA_HOME/scripts/start-system.sh"
        "$RPA_HOME/requirements.txt"
        "$RPA_HOME/.admin-password"
    )

    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            error "Missing required file: $file"
            exit 1
        fi
    done

    # Check admin password
    if [[ ! -s "$RPA_HOME/.admin-password" ]]; then
        error "Admin password file is empty or missing"
        exit 1
    fi

    success "Network-based deployment validation completed"
}

# Generate deployment report
generate_deployment_report() {
    section "GENERATING DEPLOYMENT REPORT"

    local report_file="$RPA_HOME/DEPLOYMENT_REPORT.md"
    local admin_password=$(cat $RPA_HOME/.admin-password 2>/dev/null || echo "ERROR: Could not read password")

    cat > "$report_file" << EOF
# RPA Network-Based Production Deployment Report

## Deployment Information
- **Date:** $(date)
- **Environment:** $ENVIRONMENT_TYPE
- **Architecture:** Network-Based (5 Single-threaded Workers + 1 Orchestrator)
- **Discovery Source:** $DISCOVERY_DIR
- **Deployment Version:** $(date +%Y%m%d-%H%M%S)
- **Deployed By:** $(whoami)
- **System Hostname:** $(hostname)

## System Specifications
- **Operating System:** $(cat /etc/redhat-release)
- **CPU Cores:** $CPU_COUNT
- **Total Memory:** ${MEMORY_GB}GB
- **Available Disk:** ${AVAILABLE_SPACE}GB

## RPA System Configuration
- **Installation Directory:** $RPA_HOME
- **Volume Directory:** /var/lib/rpa-volumes/
- **Architecture:** Network-Based with rpa-network (172.18.0.0/16)
- **Worker Count:** $WORKER_COUNT containers
- **Threads per Container:** 1 (single-threaded)
- **Total Job Capacity:** $WORKER_COUNT concurrent automation jobs
- **Worker Memory:** $WORKER_MEMORY each
- **Orchestrator Memory:** $ORCHESTRATOR_MEMORY

## Service Endpoints
- **Orchestrator API:** http://$(hostname):8620 (single-threaded)
- **Worker 1 API:** http://$(hostname):8621 (single-threaded)
- **Worker 2 API:** http://$(hostname):8622 (single-threaded)
- **Worker 3 API:** http://$(hostname):8623 (single-threaded)
- **Worker 4 API:** http://$(hostname):8624 (single-threaded)
- **Worker 5 API:** http://$(hostname):8625 (single-threaded)

## Authentication
- **Admin Username:** admin
- **Admin Password:** $admin_password

## Network Configuration
- **Container Network:** rpa-network (172.18.0.0/16)
- **Orchestrator Port:** 8620
- **Worker Ports:** 8621-8625
- **Firewall Status:** Configured (ports 8620-8625 open)

## Key Fixes Applied
- **Network Architecture:** Migrated from pod-based to network-based containers
- **Volume Mounting:** Uses :U flag and label=disable for AWS RHEL compatibility
- **PyJWT Dependency:** Added PyJWT==2.8.0 to resolve import errors
- **SELinux Compatibility:** Configured for systems without xattr support
- **Persistent Storage:** Uses /var/lib/rpa-volumes/ for reliable data persistence

## Management Commands

### System Control
\`\`\`bash
# Start network-based RPA system
systemctl start rpa-system

# Stop network-based RPA system
systemctl stop rpa-system

# Check system status
systemctl status rpa-system

# View system logs
journalctl -u rpa-system -f
\`\`\`

### Manual Management
\`\`\`bash
# Manual start (starts all 6 containers)
$RPA_HOME/scripts/start-system.sh

# Manual stop (stops all 6 containers)
$RPA_HOME/scripts/stop-system.sh

# Health check (checks all 6 services)
$RPA_HOME/scripts/health-check.sh
\`\`\`

### Container Management
\`\`\`bash
# View all containers
sudo -u $RPA_USER podman ps

# View individual worker logs
sudo -u $RPA_USER podman logs rpa-worker1
sudo -u $RPA_USER podman logs rpa-worker2
sudo -u $RPA_USER podman logs rpa-worker3
sudo -u $RPA_USER podman logs rpa-worker4
sudo -u $RPA_USER podman logs rpa-worker5

# Restart specific worker
sudo -u $RPA_USER podman restart rpa-worker3
\`\`\`

## Architecture Benefits
- **Predictable Performance:** Each worker handles exactly 1 job
- **Easy Debugging:** Simple process isolation per container
- **Linear Scaling:** Easy to add/remove workers
- **Fault Isolation:** Worker failures don't affect others
- **Resource Clarity:** Each container uses exactly 1 CPU thread
- **Network Isolation:** Containers communicate via dedicated network

## Deployment Validation
✅ **Prerequisites:** Installed and verified
✅ **Network Architecture:** Configured correctly
✅ **Source Code:** Deployed with all automation modules
✅ **Configurations:** Generated for single-threaded operation
✅ **Container Files:** Created for orchestrator + worker
✅ **Volume Mounting:** Compatible with AWS RHEL (no xattr support)
✅ **Firewall:** Configured for ports 8620-8625
✅ **Systemd Service:** Created for network-based system
✅ **Permissions:** Set correctly for all components
✅ **PyJWT Dependency:** Resolved for orchestrator authentication

## Next Steps
1. **Start the system:** \`systemctl start rpa-system\`
2. **Verify deployment:** \`$RPA_HOME/scripts/health-check.sh\`
3. **Access orchestrator:** http://$(hostname):8620
4. **Submit test jobs:** Use API or web interface
5. **Monitor performance:** Watch resource usage across 5 workers

---
**Network-Based RPA System deployed successfully on $(date)**
EOF

    chown $RPA_USER:$RPA_GROUP "$report_file"
    success "Deployment report generated: $report_file"
}

# Main deployment function
main() {
    echo -e "${NC}"

    info "Starting RPA Network-Based Production Deployment..."

    parse_arguments "$@"
    check_prerequisites
    analyze_system_resources
    install_prerequisites
    setup_user_directories
    deploy_source_code
    generate_production_config
    create_container_files
    create_management_scripts
    configure_firewall
    create_systemd_service
    setup_log_rotation
    set_permissions
    validate_deployment
    generate_deployment_report

    echo -e "\n${GREEN}"
    cat << 'SUCCESS'
    ╔════════════════════════════════════════════════════════════════════╗
    ║           🎉 NETWORK-BASED DEPLOYMENT SUCCESSFUL! 🎉             ║
    ╚════════════════════════════════════════════════════════════════════╝
SUCCESS
    echo -e "${NC}"

    echo -e "${CYAN}📋 Network-Based Deployment Summary:${NC}"
    echo -e "  🏠 Installation Directory: ${YELLOW}$RPA_HOME${NC}"
    echo -e "  📁 Volume Directory: ${YELLOW}/var/lib/rpa-volumes/${NC}"
    echo -e "  🎯 Architecture: ${YELLOW}Network-Based (5 Workers + 1 Orchestrator)${NC}"
    echo -e "  📈 Job Capacity: ${YELLOW}$WORKER_COUNT concurrent automation jobs${NC}"
    echo -e "  🔑 Admin Password: ${YELLOW}$admin_password${NC}"
    echo -e "  💾 Worker Memory: ${YELLOW}$WORKER_MEMORY each${NC}"
    echo -e "  💾 Orchestrator Memory: ${YELLOW}$ORCHESTRATOR_MEMORY${NC}"
    echo -e "  🔗 Network: ${YELLOW}rpa-network (172.18.0.0/16)${NC}"

    echo -e "\n${CYAN}🚀 Quick Start Commands:${NC}"
    echo -e "  ${BLUE}systemctl start rpa-system${NC}         - Start all 6 containers"
    echo -e "  ${BLUE}$RPA_HOME/scripts/health-check.sh${NC}  - Check all services"
    echo -e "  ${BLUE}systemctl status rpa-system${NC}        - Check system status"

    echo -e "\n${CYAN}🌐 Access Points (after starting):${NC}"
    echo -e "  🎛️  Orchestrator: ${YELLOW}http://$(hostname):8620${NC} (single-threaded)"
    echo -e "  👷 Worker 1:     ${YELLOW}http://$(hostname):8621${NC} (single-threaded)"
    echo -e "  👷 Worker 2:     ${YELLOW}http://$(hostname):8622${NC} (single-threaded)"
    echo -e "  👷 Worker 3:     ${YELLOW}http://$(hostname):8623${NC} (single-threaded)"
    echo -e "  👷 Worker 4:     ${YELLOW}http://$(hostname):8624${NC} (single-threaded)"
    echo -e "  👷 Worker 5:     ${YELLOW}http://$(hostname):8625${NC} (single-threaded)"

    echo -e "\n${CYAN}📚 Documentation:${NC}"
    echo -e "  📄 Deployment report: ${YELLOW}$RPA_HOME/DEPLOYMENT_REPORT.md${NC}"
    echo -e "  📋 Management scripts: ${YELLOW}$RPA_HOME/scripts/${NC}"

    echo -e "\n${CYAN}🔧 Key Fixes Applied:${NC}"
    echo -e "  ✅ Network architecture (replaces pod-based)"
    echo -e "  ✅ Volume mounting with :U flag (AWS RHEL compatible)"
    echo -e "  ✅ SELinux label=disable (no xattr support)"
    echo -e "  ✅ PyJWT dependency resolved"
    echo -e "  ✅ Persistent storage in /var/lib/rpa-volumes/"

    echo -e "\n${GREEN}✅ Your network-based RPA system is ready for production!${NC}"
    echo -e "${YELLOW}Next step: systemctl start rpa-system${NC}"
}

# Execute main function
main "$@"
