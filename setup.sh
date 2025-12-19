#!/usr/bin/env bash
# Wi-Fi Dashboard v2 Setup Script
# One-line installer for containerized architecture

set -Eeuo pipefail

REPO_URL="${REPO_URL:-https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main}"
PI_USER="${PI_USER:-$(getent passwd 1000 | cut -d: -f1 2>/dev/null || echo 'pi')}"
PI_HOME="/home/$PI_USER"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

print_banner() {
    echo -e "${BLUE}"
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║              🌐 Wi-Fi Dashboard v2.0 - Containerized             ║
║                    Manager-Worker Architecture                    ║
╚══════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
}

check_prerequisites() {
    log_step "Checking prerequisites..."
    
    if [[ $EUID -ne 0 ]]; then
        log_error "This installer must be run as root (use: sudo bash setup.sh)"
        exit 1
    fi
    
    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        log_info "Docker not found, will install..."
        INSTALL_DOCKER=true
    else
        INSTALL_DOCKER=false
        log_info "Docker found: $(docker --version)"
    fi
    
    # Check if Docker Compose is installed
    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_info "Docker Compose not found, will install..."
        INSTALL_COMPOSE=true
    else
        INSTALL_COMPOSE=false
        log_info "Docker Compose found"
    fi
    
    # Network check
    if ! curl -fsSL --max-time 10 https://google.com >/dev/null; then
        log_error "Internet connection required for installation"
        exit 1
    fi
    
    log_info "✅ Prerequisites check passed"
}

install_docker() {
    if [ "$INSTALL_DOCKER" = false ]; then
        return
    fi
    
    log_step "Installing Docker..."
    
    # Install Docker using official script
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh
    
    # Add user to docker group
    usermod -aG docker "$PI_USER"
    
    # Start Docker service
    systemctl enable docker
    systemctl start docker
    
    log_info "✅ Docker installed"
}

install_docker_compose() {
    if [ "$INSTALL_COMPOSE" = false ]; then
        return
    fi
    
    log_step "Installing Docker Compose..."
    
    # Install docker-compose-plugin (newer method)
    apt-get update
    apt-get install -y docker-compose-plugin
    
    # Also install standalone for compatibility
    if ! command -v docker-compose &> /dev/null; then
        curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
            -o /usr/local/bin/docker-compose
        chmod +x /usr/local/bin/docker-compose
    fi
    
    log_info "✅ Docker Compose installed"
}

cleanup_old_installation() {
    log_step "Cleaning up old systemd-based installation..."
    
    # Stop old services
    local services=(wifi-dashboard wifi-good wifi-bad wired-test)
    for service in "${services[@]}"; do
        systemctl stop "${service}.service" 2>/dev/null || true
        systemctl disable "${service}.service" 2>/dev/null || true
    done
    
    # Remove old service files
    rm -f /etc/systemd/system/wifi-*.service
    rm -f /etc/systemd/system/wired-test.service
    systemctl daemon-reload
    
    # Disconnect Wi-Fi interfaces
    if command -v nmcli >/dev/null 2>&1; then
        for iface in wlan0 wlan1 wlan2 wlan3; do
            nmcli dev disconnect "$iface" 2>/dev/null || true
        done
    fi
    
    log_info "✅ Old installation cleaned up"
}

setup_directories() {
    log_step "Setting up directories..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    mkdir -p "$WORK_DIR"/{configs,logs,stats,state}
    
    log_info "✅ Directories created: $WORK_DIR"
}

build_images() {
    log_step "Building Docker images..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    cd "$WORK_DIR" || exit 1
    
    # Build persona image
    log_info "Building persona image..."
    docker build -f Dockerfile.persona -t wifi-dashboard-persona:latest .
    
    # Build manager image
    log_info "Building manager image..."
    docker build -f Dockerfile.manager -t wifi-dashboard-manager:latest .
    
    log_info "✅ Docker images built"
}

start_manager() {
    log_step "Starting manager container..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    cd "$WORK_DIR" || exit 1
    
    # Start with docker-compose
    docker-compose up -d manager
    
    # Wait for manager to be ready
    log_info "Waiting for manager to start..."
    sleep 5
    
    if docker ps | grep -q wifi-manager; then
        log_info "✅ Manager container started"
    else
        log_error "❌ Manager container failed to start"
        docker-compose logs manager
        exit 1
    fi
}

show_completion() {
    local ip
    ip="$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")"
    
    echo
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    🎉 INSTALLATION COMPLETE!                    ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo
    
    if [[ -n "$ip" ]]; then
        log_info "🌐 Dashboard URL: http://${ip}:5000"
    else
        log_info "🌐 Dashboard URL: http://<your-pi-ip>:5000"
    fi
    
    echo
    log_info "📋 What's been installed:"
    log_info "  ✅ Docker and Docker Compose"
    log_info "  ✅ Manager container (Dashboard + API)"
    log_info "  ✅ Persona container image (for client simulation)"
    log_info "  ✅ Containerized architecture with interface namespace management"
    echo
    log_info "🚀 Next Steps:"
    log_info "  1. Open the dashboard URL above in your browser"
    log_info "  2. Navigate to the 'Wi-Fi Config' tab"
    log_info "  3. Enter your Wi-Fi network SSID and password"
    log_info "  4. Go to 'Personas' tab to start client simulations"
    log_info "  5. Assign personas to your available Wi-Fi interfaces"
    echo
    log_info "🔧 Useful Commands:"
    log_info "  • View manager logs: docker logs wifi-manager -f"
    log_info "  • List personas: docker ps | grep persona"
    log_info "  • Stop all: docker-compose -f $PI_HOME/wifi_dashboard_v2/docker-compose.yml down"
    echo
}

main() {
    print_banner
    
    log_info "Starting Wi-Fi Dashboard v2 installation..."
    log_info "Target user: $PI_USER"
    log_info "Repository: $REPO_URL"
    echo
    
    check_prerequisites
    install_docker
    install_docker_compose
    cleanup_old_installation
    setup_directories
    build_images
    start_manager
    
    show_completion
}

main "$@"
