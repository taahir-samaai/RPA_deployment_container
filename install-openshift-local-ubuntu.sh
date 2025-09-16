#!/bin/bash
# Install OpenShift Local (CRC) on Ubuntu for RPA Testing
# Optimized for systems with 31GB RAM

set -euo pipefail

# Configuration - Optimized for your system
CRC_VERSION="2.30.0"
CRC_MEMORY="18432"  # 18GB RAM for CRC (leaves 13GB for Ubuntu)
CRC_CPUS="6"        # 6 CPU cores (leaves 2 for Ubuntu)
CRC_DISK="120"      # 120GB disk space
PULL_SECRET_FILE=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

section() {
    echo -e "\n${CYAN}================================================${NC}"
    echo -e "${CYAN} $1 ${NC}"
    echo -e "${CYAN}================================================${NC}"
}

usage() {
    cat << EOF
Install OpenShift Local on Ubuntu 24.04

Usage: $0 [OPTIONS]

OPTIONS:
  --pull-secret FILE          Path to Red Hat pull secret (required)
  --memory SIZE              Memory in MB for CRC (default: 18432)
  --cpus COUNT               CPU count for CRC (default: 6)
  --help                     Show this help message

EXAMPLES:
  $0 --pull-secret ~/Downloads/pull-secret.txt
  $0 --pull-secret ~/Downloads/pull-secret.txt --memory 20480 --cpus 7

Get your pull secret from: https://console.redhat.com/openshift/create/local
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --pull-secret)
                PULL_SECRET_FILE="$2"
                shift 2
                ;;
            --memory)
                CRC_MEMORY="$2"
                shift 2
                ;;
            --cpus)
                CRC_CPUS="$2"
                shift 2
                ;;
            --help)
                usage
                exit 0
                ;;
            *)
                error "Unknown option: $1"
                ;;
        esac
    done

    if [[ -z "$PULL_SECRET_FILE" ]]; then
        error "Pull secret file is required. Get it from https://console.redhat.com/openshift/create/local"
    fi

    if [[ ! -f "$PULL_SECRET_FILE" ]]; then
        error "Pull secret file not found: $PULL_SECRET_FILE"
    fi
}

check_prerequisites() {
    section "CHECKING SYSTEM PREREQUISITES"

    # Check if running as regular user
    if [[ $EUID -eq 0 ]]; then
        error "Do not run this script as root. Run as your regular user."
    fi

    info "Detected Ubuntu $(lsb_release -rs) with $(nproc) cores and $(($(free -m | awk '/^Mem:/ {print $2}') / 1024))GB RAM"

    # Check virtualization
    if ! grep -q -E '(vmx|svm)' /proc/cpuinfo; then
        error "Hardware virtualization not available"
    fi

    success "System prerequisites check passed"
}

install_dependencies() {
    section "INSTALLING SYSTEM DEPENDENCIES"

    info "Updating package lists..."
    sudo apt update

    info "Installing virtualization and development tools..."
    sudo apt install -y \
        curl wget tar unzip jq \
        qemu-kvm libvirt-daemon-system libvirt-clients \
        bridge-utils cpu-checker virt-manager \
        net-tools dnsmasq

    # Configure user for virtualization
    sudo usermod -a -G libvirt "$USER"
    sudo usermod -a -G kvm "$USER"

    # Enable and start libvirt
    sudo systemctl enable --now libvirtd
    sudo systemctl start libvirtd

    # Test KVM
    if ! kvm-ok | grep -q "KVM acceleration can be used"; then
        error "KVM acceleration not available"
    fi

    success "Dependencies installed successfully"
}

download_and_install_crc() {
    section "DOWNLOADING AND INSTALLING CRC"

    cd ~/Downloads

    # Download CRC
    info "Downloading OpenShift Local ${CRC_VERSION}..."
    wget -q --show-progress \
        "https://mirror.openshift.com/pub/openshift-v4/clients/crc/${CRC_VERSION}/crc-linux-amd64.tar.xz"

    # Extract CRC
    info "Extracting CRC..."
    tar -xf crc-linux-amd64.tar.xz

    # Install CRC
    sudo cp "crc-linux-${CRC_VERSION}-amd64/crc" /usr/local/bin/
    sudo chmod +x /usr/local/bin/crc

    # Download and install oc CLI
    info "Downloading OpenShift CLI..."
    wget -q --show-progress \
        "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz"
    tar -xzf openshift-client-linux.tar.gz
    sudo cp oc kubectl /usr/local/bin/
    sudo chmod +x /usr/local/bin/{oc,kubectl}

    # Verify installation
    crc version
    oc version --client

    success "CRC and OpenShift CLI installed"
}

configure_and_start_crc() {
    section "CONFIGURING AND STARTING CRC"

    info "Configuring CRC with ${CRC_MEMORY}MB RAM and ${CRC_CPUS} CPUs..."
    crc config set memory "$CRC_MEMORY"
    crc config set cpus "$CRC_CPUS"
    crc config set disk-size "$CRC_DISK"
    crc config set enable-cluster-monitoring true
    crc config set consent-telemetry no

    info "Setting up CRC (downloading VM bundle ~4GB)..."
    crc setup

    info "Starting OpenShift cluster (this takes 10-15 minutes)..."
    info "☕ Perfect time for a coffee break!"
    crc start --pull-secret-file "$PULL_SECRET_FILE"

    # Configure oc environment
    eval $(crc oc-env)

    success "OpenShift Local cluster is running!"
}

install_keda_operator() {
    section "INSTALLING KEDA OPERATOR"

    # Login as admin
    local kubeadmin_pass=$(crc console --credentials | grep kubeadmin | awk '{print $2}')
    oc login -u kubeadmin -p "$kubeadmin_pass"

    info "Installing KEDA operator for autoscaling..."
    cat << 'EOF' | oc apply -f -
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: keda
  namespace: openshift-operators
spec:
  channel: stable
  name: keda
  source: community-operators
  sourceNamespace: openshift-marketplace
EOF

    info "Waiting for KEDA operator to be ready..."
    sleep 30
    oc wait --for=condition=Ready pod -l name=keda-operator -n openshift-operators --timeout=300s

    success "KEDA operator installed and ready"
}

create_rpa_project() {
    section "CREATING RPA TEST PROJECT"

    oc new-project rpa-test \
        --display-name="RPA Test Environment" \
        --description="Testing environment for RPA deployment with Selenium Grid 4"
    
    oc label namespace rpa-test monitoring=enabled

    success "RPA test project created"
}

setup_environment() {
    section "CONFIGURING DEVELOPMENT ENVIRONMENT"

    # Add environment setup to bashrc
    cat >> ~/.bashrc << 'EOF'

# OpenShift Local (CRC) Environment
if command -v crc &> /dev/null; then
    eval $(crc oc-env 2>/dev/null) || true
fi

# RPA Development Aliases
alias crc-status='crc status'
alias crc-console='crc console'
alias crc-start='crc start'
alias crc-stop='crc stop'
alias rpa-login='eval $(crc oc-env) && oc login -u kubeadmin -p $(crc console --credentials | grep kubeadmin | awk "{print \$2}")'
alias rpa-status='oc get pods -n rpa-test'
alias rpa-logs='oc logs -l app=rpa-orchestrator -f -n rpa-test'
alias rpa-console='echo "Console: $(crc console --url)"'
EOF

    success "Development environment configured"
}

display_completion_info() {
    section "INSTALLATION COMPLETE"

    local console_url=$(crc console --url)
    local kubeadmin_pass=$(crc console --credentials | grep kubeadmin | awk '{print $2}')

    echo -e "${GREEN}🎉 OpenShift Local is ready for RPA testing! 🎉${NC}\n"

    echo -e "${CYAN}🖥️  Cluster Information:${NC}"
    echo -e "  Console URL: ${YELLOW}$console_url${NC}"
    echo -e "  Username: ${YELLOW}kubeadmin${NC}"
    echo -e "  Password: ${YELLOW}$kubeadmin_pass${NC}"

    echo -e "\n${CYAN}⚙️  Resource Allocation:${NC}"
    echo -e "  Memory: ${YELLOW}${CRC_MEMORY}MB (18GB)${NC}"
    echo -e "  CPUs: ${YELLOW}${CRC_CPUS}${NC}"
    echo -e "  Disk: ${YELLOW}${CRC_DISK}GB${NC}"

    echo -e "\n${CYAN}🚀 Quick Start Commands:${NC}"
    echo -e "  Check status: ${BLUE}crc-status${NC}"
    echo -e "  Open console: ${BLUE}crc-console${NC}"
    echo -e "  Login CLI: ${BLUE}rpa-login${NC}"
    echo -e "  View RPA pods: ${BLUE}rpa-status${NC}"

    echo -e "\n${CYAN}🧪 Ready for RPA Testing:${NC}"
    echo -e "  ✅ OpenShift cluster running"
    echo -e "  ✅ KEDA operator installed"
    echo -e "  ✅ RPA test project created"
    echo -e "  ✅ CLI tools configured"

    echo -e "\n${CYAN}📋 Next Steps:${NC}"
    echo -e "  1. ${BLUE}Open a new terminal${NC} (to load new environment)"
    echo -e "  2. ${BLUE}rpa-login${NC} (to login to OpenShift)"
    echo -e "  3. Copy your RPA source code and deployment script"
    echo -e "  4. Run your enhanced-openshift-rpa-deployment.sh script"

    echo -e "\n${YELLOW}💡 Tips:${NC}"
    echo -e "  • Use 'crc stop' when not testing to save resources"
    echo -e "  • First startup after reboot takes ~5 minutes"
    echo -e "  • Console and CLI are both available for management"
}

main() {
    echo -e "${CYAN}"
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════════╗
║              🚀 OpenShift Local Setup for Ubuntu 24.04 🚀            ║
║                                                                      ║
║    ✨ Single-node OpenShift cluster on your laptop                   ║
║    ✨ KEDA operator for intelligent autoscaling                       ║
║    ✨ Ready for Selenium Grid 4 + RPA testing                        ║
║    ✨ Optimized for your 31GB/8-core system                          ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"

    parse_arguments "$@"
    check_prerequisites
    install_dependencies
    download_and_install_crc
    configure_and_start_crc
    install_keda_operator
    create_rpa_project
    setup_environment
    display_completion_info

    echo -e "\n${GREEN}🎯 OpenShift Local installation completed successfully!${NC}"
    echo -e "${BLUE}💫 Open a new terminal and run 'rpa-login' to get started!${NC}"
}

# Handle script interruption gracefully
trap 'echo -e "\n${YELLOW}Installation interrupted. You can resume by running this script again.${NC}"; exit 1' INT

main "$@"
