#!/bin/bash
# RPA Environment Discovery Script
# Captures complete current environment for production deployment

set -e

# Configuration
OUTPUT_DIR="$(pwd)/environment-discovery-$(date +%Y%m%d-%H%M%S)"
DISCOVERY_LOG="$OUTPUT_DIR/discovery.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$DISCOVERY_LOG"
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

section() {
    echo -e "\n${CYAN}================================================${NC}"
    echo -e "${CYAN} $1 ${NC}"
    echo -e "${CYAN}================================================${NC}"
    log "SECTION: $1"
}

# Initialize output directory
mkdir -p "$OUTPUT_DIR"/{system,containers,network,volumes,config,source}
info "Created discovery directory: $OUTPUT_DIR"

# Function to safely run commands and capture output
safe_capture() {
    local cmd="$1"
    local output_file="$2"
    local description="$3"
    
    info "Capturing: $description"
    echo "# $description" > "$output_file"
    echo "# Command: $cmd" >> "$output_file"
    echo "# Generated: $(date)" >> "$output_file"
    echo "" >> "$output_file"
    
    if eval "$cmd" >> "$output_file" 2>&1; then
        success "Captured: $description"
    else
        warning "Failed to capture: $description"
        echo "# ERROR: Command failed" >> "$output_file"
    fi
    echo -e "\n" >> "$output_file"
}

# Function to capture file if it exists
safe_copy_file() {
    local source="$1"
    local dest="$2"
    local description="$3"
    
    if [[ -f "$source" ]]; then
        info "Copying: $description"
        cp "$source" "$dest"
        success "Copied: $description"
    else
        warning "File not found: $source ($description)"
        echo "# File not found: $source" > "$dest"
        echo "# Description: $description" >> "$dest"
    fi
}

#=================================================
# SYSTEM INFORMATION
#=================================================
section "SYSTEM INFORMATION"

safe_capture "hostnamectl" "$OUTPUT_DIR/system/hostnamectl.txt" "System hostname and OS info"
safe_capture "uname -a" "$OUTPUT_DIR/system/kernel.txt" "Kernel information"
safe_capture "lscpu" "$OUTPUT_DIR/system/cpu.txt" "CPU information"
safe_capture "free -h" "$OUTPUT_DIR/system/memory.txt" "Memory information"
safe_capture "df -h" "$OUTPUT_DIR/system/disk.txt" "Disk usage"
safe_capture "lsblk" "$OUTPUT_DIR/system/block_devices.txt" "Block devices"
safe_capture "id" "$OUTPUT_DIR/system/current_user.txt" "Current user information"
safe_capture "cat /etc/redhat-release" "$OUTPUT_DIR/system/os_release.txt" "OS release"
safe_capture "rpm -qa | grep -E '(podman|container|buildah|skopeo)' | sort" "$OUTPUT_DIR/system/container_packages.txt" "Container-related packages"

#=================================================
# PODMAN SYSTEM INFORMATION
#=================================================
section "PODMAN SYSTEM INFORMATION"

safe_capture "podman version" "$OUTPUT_DIR/system/podman_version.txt" "Podman version"
safe_capture "podman system info" "$OUTPUT_DIR/system/podman_info.txt" "Podman system info"
safe_capture "podman system df" "$OUTPUT_DIR/system/podman_disk_usage.txt" "Podman disk usage"

#=================================================
# CONTAINER INFORMATION
#=================================================
section "CONTAINER INFORMATION"

safe_capture "podman ps -a" "$OUTPUT_DIR/containers/containers_list.txt" "All containers"
safe_capture "podman ps -a --format 'table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'" "$OUTPUT_DIR/containers/containers_table.txt" "Containers formatted table"

# Get list of RPA containers (adjust pattern if needed)
RPA_CONTAINERS=$(podman ps -a --format "{{.Names}}" | grep -E "(rpa|orchestrator|worker)" || echo "")

if [[ -n "$RPA_CONTAINERS" ]]; then
    info "Found RPA containers: $RPA_CONTAINERS"
    
    for container in $RPA_CONTAINERS; do
        info "Processing container: $container"
        mkdir -p "$OUTPUT_DIR/containers/$container"
        
        # Container inspection
        safe_capture "podman inspect $container" "$OUTPUT_DIR/containers/$container/inspect.json" "Container inspection for $container"
        
        # Container environment variables
        safe_capture "podman exec $container env 2>/dev/null || echo 'Container not running or accessible'" "$OUTPUT_DIR/containers/$container/environment.txt" "Environment variables for $container"
        
        # Container process list
        safe_capture "podman exec $container ps aux 2>/dev/null || echo 'Container not running or accessible'" "$OUTPUT_DIR/containers/$container/processes.txt" "Processes in $container"
        
        # Container logs (last 100 lines)
        safe_capture "podman logs --tail 100 $container 2>/dev/null || echo 'No logs available'" "$OUTPUT_DIR/containers/$container/logs.txt" "Recent logs for $container"
        
        # Container stats (if running)
        safe_capture "podman stats --no-stream $container 2>/dev/null || echo 'Container not running'" "$OUTPUT_DIR/containers/$container/stats.txt" "Resource stats for $container"
    done
else
    warning "No RPA containers found. Capturing all containers."
    for container in $(podman ps -a --format "{{.Names}}" 2>/dev/null || echo ""); do
        if [[ -n "$container" && "$container" != "NAMES" ]]; then
            mkdir -p "$OUTPUT_DIR/containers/$container"
            safe_capture "podman inspect $container" "$OUTPUT_DIR/containers/$container/inspect.json" "Container inspection for $container"
        fi
    done
fi

#=================================================
# IMAGES INFORMATION
#=================================================
section "IMAGES INFORMATION"

safe_capture "podman images" "$OUTPUT_DIR/containers/images_list.txt" "All images"
safe_capture "podman images --format 'table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Created}}\t{{.Size}}'" "$OUTPUT_DIR/containers/images_table.txt" "Images formatted table"

# Capture image history for RPA images
RPA_IMAGES=$(podman images --format "{{.Repository}}:{{.Tag}}" | grep -E "(rpa|orchestrator|worker)" || echo "")

if [[ -n "$RPA_IMAGES" ]]; then
    for image in $RPA_IMAGES; do
        safe_capture "podman history $image" "$OUTPUT_DIR/containers/history_${image//[:\/]/_}.txt" "Build history for $image"
    done
fi

#=================================================
# NETWORK INFORMATION
#=================================================
section "NETWORK INFORMATION"

safe_capture "podman network ls" "$OUTPUT_DIR/network/networks_list.txt" "Podman networks"

# Get network details for each network
for network in $(podman network ls --format "{{.Name}}" 2>/dev/null || echo ""); do
    if [[ "$network" != "NAME" ]]; then
        safe_capture "podman network inspect $network" "$OUTPUT_DIR/network/network_${network}.json" "Network details for $network"
    fi
done

# System network information
safe_capture "ip addr show" "$OUTPUT_DIR/network/ip_addresses.txt" "IP addresses"
safe_capture "ip route show" "$OUTPUT_DIR/network/routes.txt" "Network routes"
safe_capture "ss -tuln" "$OUTPUT_DIR/network/listening_ports.txt" "Listening ports"

#=================================================
# VOLUMES AND STORAGE
#=================================================
section "VOLUMES AND STORAGE"

safe_capture "podman volume ls" "$OUTPUT_DIR/volumes/volumes_list.txt" "Podman volumes"

# Get volume details
for volume in $(podman volume ls --format "{{.Name}}" 2>/dev/null || echo ""); do
    if [[ "$volume" != "VOLUME" && "$volume" != "NAME" ]]; then
        safe_capture "podman volume inspect $volume" "$OUTPUT_DIR/volumes/volume_${volume}.json" "Volume details for $volume"
    fi
done

# Find mount points used by RPA containers
info "Analyzing mount points..."
if [[ -n "$RPA_CONTAINERS" ]]; then
    for container in $RPA_CONTAINERS; do
        podman inspect "$container" 2>/dev/null | jq -r '.[].Mounts[]? | "\(.Source) -> \(.Destination)"' > "$OUTPUT_DIR/volumes/mounts_${container}.txt" 2>/dev/null || echo "No mounts found" > "$OUTPUT_DIR/volumes/mounts_${container}.txt"
    done
fi

#=================================================
# CONFIGURATION FILES DISCOVERY
#=================================================
section "CONFIGURATION FILES DISCOVERY"

# Look specifically in your RPA system directory
RPA_SYSTEM_DIR="/root/rpa-system"
CONFIG_LOCATIONS=(
    "$RPA_SYSTEM_DIR"
    "/opt/rpa-system"
    "/home/$(logname 2>/dev/null || echo root)/rpa"
    "/home/$(logname 2>/dev/null || echo root)/rpa-system"
    "$(pwd)"
    "/etc/systemd/system/rpa*"
)

info "Searching for RPA configuration files..."

# First, document your specific RPA system structure
if [[ -d "$RPA_SYSTEM_DIR" ]]; then
    info "Found RPA system directory: $RPA_SYSTEM_DIR"
    safe_capture "find $RPA_SYSTEM_DIR -type f \( -name '*.py' -o -name '*.env' -o -name '*.conf' -o -name '*.yaml' -o -name '*.yml' -o -name '*.json' -o -name 'Containerfile' -o -name 'Dockerfile' -o -name 'docker-compose.*' -o -name 'requirements.txt' -o -name '*.sh' \) 2>/dev/null | sort" "$OUTPUT_DIR/config/found_files.txt" "RPA system files"
fi

for location in "${CONFIG_LOCATIONS[@]}"; do
    if [[ -d "$location" ]]; then
        info "Searching directory: $location"
        find "$location" -type f \( -name "*.py" -o -name "*.env" -o -name "*.conf" -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" -o -name "Containerfile" -o -name "Dockerfile" -o -name "docker-compose.*" -o -name "requirements.txt" -o -name "*.sh" \) 2>/dev/null >> "$OUTPUT_DIR/config/found_files.txt" || true
    elif [[ -f "$location" ]]; then
        info "Found file: $location"
        echo "$location" >> "$OUTPUT_DIR/config/found_files.txt"
    fi
done

# Copy found configuration files
info "Copying configuration files..."
mkdir -p "$OUTPUT_DIR/config/files"

if [[ -f "$OUTPUT_DIR/config/found_files.txt" ]]; then
    while read -r file; do
        if [[ -f "$file" ]]; then
            # Create relative directory structure
            relative_path="${file#/}"
            target_dir="$OUTPUT_DIR/config/files/$(dirname "$relative_path")"
            mkdir -p "$target_dir"
            cp "$file" "$target_dir/" 2>/dev/null || warning "Could not copy $file"
        fi
    done < "$OUTPUT_DIR/config/found_files.txt"
fi

#=================================================
# BUILD CONTEXT DISCOVERY
#=================================================
section "BUILD CONTEXT DISCOVERY"

# Look for source code and build files
info "Searching for source code and build context..."

SEARCH_DIRS=(
    "/root/rpa-system"
    "/opt/rpa-system"
    "$(pwd)"
)

for search_dir in "${SEARCH_DIRS[@]}"; do
    if [[ -d "$search_dir" ]]; then
        info "Searching in: $search_dir"
        
        # Find Python files
        find "$search_dir" -name "*.py" -type f 2>/dev/null | head -50 >> "$OUTPUT_DIR/source/python_files.txt" || true
        
        # Find requirement files
        find "$search_dir" -name "requirements*.txt" -type f 2>/dev/null >> "$OUTPUT_DIR/source/requirements_files.txt" || true
        
        # Find container files
        find "$search_dir" \( -name "Containerfile" -o -name "Dockerfile" -o -name "docker-compose*" \) -type f 2>/dev/null >> "$OUTPUT_DIR/source/container_files.txt" || true
        
        # Directory structure
        echo "=== Directory: $search_dir ===" >> "$OUTPUT_DIR/source/directory_structure.txt"
        tree "$search_dir" -L 3 2>/dev/null >> "$OUTPUT_DIR/source/directory_structure.txt" || ls -la "$search_dir" >> "$OUTPUT_DIR/source/directory_structure.txt"
        echo "" >> "$OUTPUT_DIR/source/directory_structure.txt"
    fi
done

#=================================================
# SYSTEMD SERVICES
#=================================================
section "SYSTEMD SERVICES"

safe_capture "systemctl list-units '*rpa*' --all" "$OUTPUT_DIR/system/rpa_services.txt" "RPA systemd services"
safe_capture "systemctl list-units '*container*' --all" "$OUTPUT_DIR/system/container_services.txt" "Container-related services"

# Check for specific service files
for service_file in /etc/systemd/system/rpa*.service /etc/systemd/system/*rpa*.service; do
    if [[ -f "$service_file" ]]; then
        safe_copy_file "$service_file" "$OUTPUT_DIR/config/files/$(basename "$service_file")" "Systemd service file"
    fi
done

#=================================================
# FIREWALL AND SECURITY
#=================================================
section "FIREWALL AND SECURITY"

safe_capture "firewall-cmd --list-all 2>/dev/null || echo 'Firewall not running or not available'" "$OUTPUT_DIR/system/firewall.txt" "Firewall configuration"
safe_capture "getenforce 2>/dev/null || echo 'SELinux not available'" "$OUTPUT_DIR/system/selinux_mode.txt" "SELinux enforcement mode"
safe_capture "sestatus 2>/dev/null || echo 'SELinux not available'" "$OUTPUT_DIR/system/selinux_status.txt" "SELinux status"

#=================================================
# CURRENT RUNNING PROCESSES
#=================================================
section "RUNNING PROCESSES"

safe_capture "ps aux | grep -E '(rpa|orchestrator|worker|python)' | grep -v grep" "$OUTPUT_DIR/system/rpa_processes.txt" "RPA-related processes"

#=================================================
# GENERATE SUMMARY REPORT
#=================================================
section "GENERATING SUMMARY REPORT"

cat > "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md" << 'SUMMARY_EOF'
# RPA System Environment Discovery Report

## Overview
This report contains a complete snapshot of the current RPA system environment.

## Files Structure
```
environment-discovery-[timestamp]/
├── system/                    # System information
├── containers/               # Container details
├── network/                  # Network configuration  
├── volumes/                  # Volume and mount information
├── config/                   # Configuration files
├── source/                   # Source code discovery
└── ENVIRONMENT_SUMMARY.md    # This file
```

## Key Components Discovered

### System Information
- OS and kernel details
- Hardware specifications
- Installed packages

### Container Architecture
SUMMARY_EOF

if [[ -n "$RPA_CONTAINERS" ]]; then
    echo "- **RPA Containers Found:** $RPA_CONTAINERS" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
else
    echo "- **No RPA containers currently running** - Check config/files for container definitions" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
fi

cat >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md" << 'SUMMARY_EOF2'

### RPA System Directory Structure
Based on discovery, your RPA system appears to be located at:
- `/root/rpa-system/` - Main RPA system directory

Key components found:
- Configuration files in `configs/` directory
- Container definitions in `containers/` directory  
- Scripts in `scripts/` directory
- Data volumes in `volumes/` directory
- Python automation modules

### Network Configuration
- Podman networks and bridges
- Port mappings and routing
- Active listening services

### Storage and Volumes
- Volume mounts and bind mounts
- Data persistence locations
- File permissions and ownership

### Build Context
- Source code locations
- Container build files
- Dependencies and requirements

## Next Steps for Production Deployment

1. **Review Configuration Files:**
   - Check `config/files/` directory
   - Verify environment variables and secrets
   - Update URLs and endpoints for production

2. **Prepare Container Images:**
   - Review build context in `source/` directory
   - Build and tag images for production
   - Set up image registry if needed

3. **Network Planning:**
   - Review network configuration in `network/`
   - Plan production network topology
   - Configure firewall rules

4. **Data Migration:**
   - Review volume mounts in `volumes/`
   - Plan data migration strategy
   - Set up backup and recovery procedures

5. **Resource Planning:**
   - Review system specifications in `system/`
   - Size production VM appropriately
   - Plan for monitoring and scaling

## Important Notes

- **Secrets and Passwords:** Review all configuration files for hardcoded secrets
- **IP Addresses:** Update any hardcoded IP addresses for production environment  
- **File Paths:** Verify all file paths work in production environment
- **Permissions:** Ensure proper user and group permissions in production
- **Dependencies:** Install all required packages and dependencies

SUMMARY_EOF2

# Add container summary if found
if [[ -n "$RPA_CONTAINERS" ]]; then
    echo -e "\n### Container Summary\n" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
    
    for container in $RPA_CONTAINERS; do
        if [[ -f "$OUTPUT_DIR/containers/$container/inspect.json" ]]; then
            echo "#### $container" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
            
            # Extract key information from container inspect (handle potential jq issues)
            IMAGE=$(jq -r '.[].Config.Image' "$OUTPUT_DIR/containers/$container/inspect.json" 2>/dev/null || echo "Unknown")
            PORTS=$(jq -r '.[].NetworkSettings.Ports | keys[]?' "$OUTPUT_DIR/containers/$container/inspect.json" 2>/dev/null | tr '\n' ' ' || echo "None")
            
            echo "- **Image:** $IMAGE" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
            echo "- **Ports:** $PORTS" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
            echo "" >> "$OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
        fi
    done
fi

#=================================================
# CREATE DEPLOYMENT CHECKLIST
#=================================================
cat > "$OUTPUT_DIR/DEPLOYMENT_CHECKLIST.md" << 'CHECKLIST_EOF'
# Production Deployment Checklist

## Pre-Deployment
- [ ] Review environment discovery report
- [ ] Provision production VM with adequate resources
- [ ] Install RHEL and required packages
- [ ] Set up user accounts and permissions
- [ ] Configure firewall and security

## Container Preparation  
- [ ] Build container images for production
- [ ] Test images in staging environment
- [ ] Set up container registry (if needed)
- [ ] Tag images with production versions

## Configuration Management
- [ ] Update environment variables for production
- [ ] Replace development URLs/endpoints
- [ ] Generate production secrets and passwords
- [ ] Configure SSL/TLS certificates (if needed)
- [ ] Set up logging and monitoring

## Network Configuration
- [ ] Configure production network topology
- [ ] Set up load balancer (if needed)  
- [ ] Configure DNS records
- [ ] Test network connectivity
- [ ] Configure firewall rules

## Data Management
- [ ] Set up data directories with correct permissions
- [ ] Configure data backup strategy
- [ ] Test data migration procedures
- [ ] Set up log rotation
- [ ] Configure monitoring and alerting

## Service Configuration
- [ ] Create systemd service files
- [ ] Configure service dependencies
- [ ] Test service start/stop/restart
- [ ] Configure auto-start on boot
- [ ] Set up health checks

## Testing and Validation
- [ ] Deploy to staging environment first
- [ ] Run smoke tests
- [ ] Validate all endpoints
- [ ] Test failover scenarios
- [ ] Performance testing
- [ ] Security testing

## Go-Live
- [ ] Deploy to production
- [ ] Monitor system startup
- [ ] Validate all services are healthy
- [ ] Test end-to-end workflows
- [ ] Document any issues and resolutions
- [ ] Set up ongoing monitoring

## Post-Deployment
- [ ] Monitor system performance
- [ ] Review logs for errors
- [ ] Document production procedures
- [ ] Train operations team
- [ ] Schedule regular maintenance
CHECKLIST_EOF

success "Environment discovery completed!"
info "Discovery report saved to: $OUTPUT_DIR"
info "Review the following key files:"
info "  - $OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
info "  - $OUTPUT_DIR/DEPLOYMENT_CHECKLIST.md"

echo -e "\n${GREEN}🎉 Discovery completed successfully!${NC}"
echo -e "${CYAN}Files created in: $OUTPUT_DIR${NC}"
echo -e "${CYAN}Key files to review:${NC}"
echo "  📋 $OUTPUT_DIR/ENVIRONMENT_SUMMARY.md"
echo "  ✅ $OUTPUT_DIR/DEPLOYMENT_CHECKLIST.md" 
echo "  📁 $OUTPUT_DIR/config/files/ (your configuration files)"
echo -e "\n${CYAN}Next steps:${NC}"
echo "1. Review the generated files"
echo "2. Package for production deployment: tar -czf rpa-discovery-\$(date +%Y%m%d).tar.gz $OUTPUT_DIR"
echo "3. Transfer to production VM and use with deployment script"
