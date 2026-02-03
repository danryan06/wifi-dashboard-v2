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

fix_repository_issues() {
    log_info "Fixing repository issues for Debian Bullseye..."
    
    # Disable problematic backports repository
    if [[ -f /etc/apt/sources.list.d/debian-backports.list ]]; then
        log_info "  Disabling bullseye-backports repository..."
        sed -i 's/^deb/#deb/' /etc/apt/sources.list.d/debian-backports.list 2>/dev/null || true
    fi
    
    # Also check main sources.list file
    if grep -q "bullseye-backports" /etc/apt/sources.list 2>/dev/null; then
        log_info "  Disabling bullseye-backports in main sources.list..."
        sed -i 's|^deb.*bullseye-backports|#deb &|' /etc/apt/sources.list 2>/dev/null || true
    fi
    
    # Fix InfluxData GPG key if needed
    if [[ -f /etc/apt/sources.list.d/influxdb.list ]] || grep -q "repos.influxdata.com" /etc/apt/sources.list.d/*.list 2>/dev/null; then
        log_info "  Fixing InfluxData repository key..."
        curl -fsSL https://repos.influxdata.com/influxdb.key | apt-key add - 2>/dev/null || true
    fi
    
    # Fix Grafana GPG key if needed
    if grep -q "apt.grafana.com" /etc/apt/sources.list.d/*.list 2>/dev/null; then
        log_info "  Fixing Grafana repository key..."
        curl -fsSL https://apt.grafana.com/gpg.key | apt-key add - 2>/dev/null || true
    fi
    
    log_info "✅ Repository fixes applied"
}

check_prerequisites() {
    log_step "Checking prerequisites..."
    
    if [[ $EUID -ne 0 ]]; then
        log_error "This installer must be run as root (use: sudo bash setup.sh)"
        exit 1
    fi
    
    # Fix repository issues early
    fix_repository_issues
    
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
    
    # Update apt (repository issues already fixed in check_prerequisites)
    apt-get update 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG\|bullseye-backports" || true
    
    # Install Docker using official script with error handling
    log_info "Downloading Docker installation script..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh || {
        log_error "Failed to download Docker installation script"
        log_info "Attempting manual Docker installation..."
        install_docker_manual
        return
    }
    
    log_info "Running Docker installation script..."
    if sh /tmp/get-docker.sh 2>&1 | tee /tmp/docker-install.log; then
        log_info "✅ Docker installed via official script"
    else
        log_warn "Docker installation script had warnings, checking if Docker was installed..."
        if command -v docker &> /dev/null; then
            log_info "✅ Docker is installed (despite warnings)"
        else
            log_warn "Docker installation script failed, attempting manual installation..."
            install_docker_manual
            return
        fi
    fi
    
    # Add user to docker group
    usermod -aG docker "$PI_USER" 2>/dev/null || true
    
    # Start Docker service
    systemctl enable docker 2>/dev/null || true
    systemctl start docker 2>/dev/null || {
        log_error "Failed to start Docker service"
        log_info "Trying to start Docker manually..."
        service docker start || true
    }
    
    # Verify Docker is working
    if docker ps &>/dev/null; then
        log_info "✅ Docker installed and running"
    else
        log_error "Docker installed but not responding"
        log_info "You may need to log out and back in, or run: newgrp docker"
    fi
}

install_docker_manual() {
    log_step "Installing Docker manually..."
    
    # Install prerequisites
    apt-get update 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true
    apt-get install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true
    
    # Add Docker's official GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Set up repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    # Install Docker
    apt-get update 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
        2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true
    
    log_info "✅ Docker installed manually"
}

install_docker_compose() {
    if [ "$INSTALL_COMPOSE" = false ]; then
        return
    fi
    
    log_step "Installing Docker Compose..."
    
    # Check if docker-compose-plugin is already installed (installed with Docker)
    if docker compose version &>/dev/null || dpkg -l | grep -q docker-compose-plugin; then
        log_info "Docker Compose plugin already installed"
    else
        # Install docker-compose-plugin (newer method)
        log_info "Installing docker-compose-plugin..."
        apt-get update 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true
        apt-get install -y docker-compose-plugin 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || {
            log_warn "Failed to install docker-compose-plugin via apt, will try standalone version"
        }
    fi
    
    # Also install standalone for compatibility (if not already present)
    if ! command -v docker-compose &> /dev/null; then
        log_info "Installing standalone docker-compose for compatibility..."
        curl -fsSL -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
            -o /usr/local/bin/docker-compose || {
            log_warn "Failed to download standalone docker-compose, but plugin version should work"
            return 0
        }
        chmod +x /usr/local/bin/docker-compose
    fi
    
    # Verify installation
    if docker compose version &>/dev/null || command -v docker-compose &>/dev/null; then
        log_info "✅ Docker Compose installed"
    else
        log_warn "⚠️ Docker Compose installation had issues, but continuing..."
    fi
}

cleanup_old_installation() {
    log_step "Cleaning up old installations..."
    
    # ============================================
    # Cleanup v1 (systemd-based) installations
    # ============================================
    log_info "Stopping old v1 systemd services..."
    local services=(wifi-dashboard wifi-good wifi-bad wired-test traffic-eth0 traffic-wlan0 traffic-wlan1)
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            log_info "  Stopping ${service}.service..."
            systemctl stop "${service}.service" 2>/dev/null || true
        fi
        if systemctl is-enabled --quiet "${service}.service" 2>/dev/null; then
            log_info "  Disabling ${service}.service..."
            systemctl disable "${service}.service" 2>/dev/null || true
        fi
    done
    
    # Remove old service files
    log_info "Removing old systemd service files..."
    rm -f /etc/systemd/system/wifi-*.service
    rm -f /etc/systemd/system/wired-test.service
    rm -f /etc/systemd/system/traffic-*.service
    systemctl daemon-reload 2>/dev/null || true
    
    # ============================================
    # Cleanup v2 (Docker-based) installations
    # ============================================
    if command -v docker >/dev/null 2>&1; then
        log_info "Stopping existing v2 containers..."
        
        # Stop and remove manager container if it exists
        if docker ps -a --format '{{.Names}}' | grep -q '^wifi-manager$'; then
            log_info "  Stopping wifi-manager container..."
            docker stop wifi-manager 2>/dev/null || true
            docker rm wifi-manager 2>/dev/null || true
        fi
        
        # Stop and remove all persona containers
        local persona_containers
        persona_containers=$(docker ps -a --format '{{.Names}}' | grep '^persona-' 2>/dev/null || true)
        if [[ -n "$persona_containers" ]]; then
            log_info "  Stopping persona containers..."
            echo "$persona_containers" | while read -r container; do
                log_info "    Stopping $container..."
                docker stop "$container" 2>/dev/null || true
                docker rm "$container" 2>/dev/null || true
            done
        fi
        
        # Clean up docker-compose if it exists
        WORK_DIR="$PI_HOME/wifi_dashboard_v2"
        if [[ -f "$WORK_DIR/docker-compose.yml" ]]; then
            log_info "  Stopping docker-compose services..."
            cd "$WORK_DIR" && docker-compose down 2>/dev/null || true
        fi
    fi
    
    # ============================================
    # Cleanup network interfaces
    # ============================================
    log_info "Disconnecting Wi-Fi interfaces..."
    if command -v nmcli >/dev/null 2>&1; then
        for iface in wlan0 wlan1 wlan2 wlan3 wlan4 wlan5; do
            if nmcli device status 2>/dev/null | grep -q "^$iface"; then
                log_info "  Disconnecting $iface..."
                nmcli dev disconnect "$iface" 2>/dev/null || true
            fi
        done
    fi
    
    # Return any interfaces that might be stuck in container namespaces
    log_info "Checking for interfaces in container namespaces..."
    for iface in wlan0 wlan1 wlan2 wlan3 wlan4 wlan5; do
        if ! ip link show "$iface" >/dev/null 2>&1; then
            # Interface might be in a namespace, try to recover
            log_info "  Attempting to recover $iface..."
            # This is a best-effort recovery - interfaces should be returned by containers
        fi
    done
    
    # ============================================
    # Cleanup old directories (optional backup)
    # ============================================
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    OLD_DIR="$PI_HOME/wifi_test_dashboard"  # v1 directory
    
    if [[ -d "$OLD_DIR" ]]; then
        log_warn "Old v1 installation found at $OLD_DIR"
        log_info "  Backing up to ${OLD_DIR}.backup.$(date +%s)..."
        mv "$OLD_DIR" "${OLD_DIR}.backup.$(date +%s)" 2>/dev/null || true
    fi
    
    # Clean up old v2 directory if doing a fresh install
    if [[ -d "$WORK_DIR" ]] && [[ "${FORCE_CLEAN_INSTALL:-false}" == "true" ]]; then
        log_warn "Force clean install requested - backing up existing v2 installation..."
        mv "$WORK_DIR" "${WORK_DIR}.backup.$(date +%s)" 2>/dev/null || true
    fi
    
    # ============================================
    # Cleanup old Docker images (optional)
    # ============================================
    if command -v docker >/dev/null 2>&1 && [[ "${CLEAN_DOCKER_IMAGES:-false}" == "true" ]]; then
        log_info "Removing old Docker images..."
        docker rmi wifi-dashboard-manager:latest 2>/dev/null || true
        docker rmi wifi-dashboard-persona:latest 2>/dev/null || true
    fi
    
    # ============================================
    # Cleanup old log files (optional)
    # ============================================
    if [[ "${CLEAN_LOGS:-false}" == "true" ]]; then
        log_info "Cleaning up old log files..."
        find "$WORK_DIR/logs" -type f -name "*.log" -mtime +30 -delete 2>/dev/null || true
        find "$OLD_DIR/logs" -type f -name "*.log" -mtime +30 -delete 2>/dev/null || true
    fi
    
    log_info "✅ Cleanup completed"
}

setup_directories() {
    log_step "Setting up directories..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    mkdir -p "$WORK_DIR"/{configs,logs,stats,state}
    
    # Preserve existing configs if upgrading
    if [[ -f "$WORK_DIR/configs/ssid.conf" ]]; then
        log_info "Preserving existing Wi-Fi configuration..."
        cp "$WORK_DIR/configs/ssid.conf" "$WORK_DIR/configs/ssid.conf.backup.$(date +%s)" 2>/dev/null || true
    fi
    
    if [[ -f "$WORK_DIR/configs/settings.conf" ]]; then
        log_info "Preserving existing settings..."
        cp "$WORK_DIR/configs/settings.conf" "$WORK_DIR/configs/settings.conf.backup.$(date +%s)" 2>/dev/null || true
    fi
    
    # Preserve state if it exists
    if [[ -f "$WORK_DIR/state/personas.json" ]]; then
        log_info "Preserving existing persona state..."
        cp "$WORK_DIR/state/personas.json" "$WORK_DIR/state/personas.json.backup.$(date +%s)" 2>/dev/null || true
    fi
    
    log_info "✅ Directories created: $WORK_DIR"
}

download_project_files() {
    log_step "Downloading project files from repository..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    cd "$WORK_DIR" || exit 1
    
    # Download essential files for building images
    log_info "Downloading Dockerfiles and project files..."
    
    # Function to download with retry
    download_with_retry() {
        local url="$1"
        local output="$2"
        local max_attempts=3
        local attempt=1
        
        while [[ $attempt -le $max_attempts ]]; do
            if curl -fsSL "$url" -o "$output"; then
                return 0
            fi
            log_warn "Download attempt $attempt failed for $(basename "$output"), retrying..."
            sleep 2
            ((attempt++))
        done
        
        log_error "Failed to download $(basename "$output") after $max_attempts attempts"
        return 1
    }
    
    # Download Dockerfiles
    log_info "  Downloading Dockerfiles..."
    download_with_retry "${REPO_URL}/Dockerfile.persona" "Dockerfile.persona" || exit 1
    download_with_retry "${REPO_URL}/Dockerfile.manager" "Dockerfile.manager" || exit 1
    download_with_retry "${REPO_URL}/docker-compose.yml" "docker-compose.yml" || exit 1
    
    # Download persona files
    log_info "  Downloading persona scripts..."
    mkdir -p persona scripts/traffic manager/static templates
    download_with_retry "${REPO_URL}/persona/entrypoint.sh" "persona/entrypoint.sh" || exit 1
    download_with_retry "${REPO_URL}/persona/good_client.sh" "persona/good_client.sh" || exit 1
    download_with_retry "${REPO_URL}/persona/bad_client.sh" "persona/bad_client.sh" || exit 1
    download_with_retry "${REPO_URL}/persona/wired_client.sh" "persona/wired_client.sh" || exit 1
    download_with_retry "${REPO_URL}/persona/rotate_mac.sh" "persona/rotate_mac.sh" || exit 1
    
    # Download traffic script
    log_info "  Downloading traffic generation script..."
    download_with_retry "${REPO_URL}/scripts/traffic/interface_traffic_generator.sh" "scripts/traffic/interface_traffic_generator.sh" || exit 1
    
    # Download manager files
    log_info "  Downloading manager application..."
    download_with_retry "${REPO_URL}/manager/app.py" "manager/app.py" || exit 1
    download_with_retry "${REPO_URL}/manager/manager_logic.py" "manager/manager_logic.py" || exit 1
    download_with_retry "${REPO_URL}/manager/interface_manager.py" "manager/interface_manager.py" || exit 1
    download_with_retry "${REPO_URL}/manager/__init__.py" "manager/__init__.py" || exit 1
    
    # Download static files
    log_info "  Downloading static assets..."
    download_with_retry "${REPO_URL}/manager/static/dashboard.js" "manager/static/dashboard.js" || exit 1
    download_with_retry "${REPO_URL}/manager/static/dashboard.css" "manager/static/dashboard.css" || exit 1
    
    # Download template
    log_info "  Downloading templates..."
    download_with_retry "${REPO_URL}/templates/dashboard.html" "templates/dashboard.html" || exit 1
    
    # Make scripts executable
    log_info "  Setting executable permissions..."
    chmod +x persona/*.sh scripts/traffic/*.sh 2>/dev/null || true
    
    log_info "✅ Project files downloaded"
}

build_images() {
    log_step "Building Docker images..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    cd "$WORK_DIR" || exit 1
    
    # Build persona image
    log_info "Building persona image..."
    docker build -f Dockerfile.persona -t wifi-dashboard-persona:latest . || {
        log_error "Failed to build persona image"
        exit 1
    }
    
    # Build manager image
    log_info "Building manager image..."
    docker build -f Dockerfile.manager -t wifi-dashboard-manager:latest . || {
        log_error "Failed to build manager image"
        exit 1
    }
    
    log_info "✅ Docker images built"
}

start_manager() {
    log_step "Starting manager container..."
    
    WORK_DIR="$PI_HOME/wifi_dashboard_v2"
    cd "$WORK_DIR" || exit 1
    
    # Ensure Docker socket is accessible (check permissions)
    if [[ -S /var/run/docker.sock ]]; then
        log_info "Verifying Docker socket permissions..."
        # Socket should be accessible to root (which container runs as)
        # If there are issues, we'll see them in logs
    fi
    
    # Start with docker-compose
    log_info "Starting manager container..."
    docker-compose up -d manager
    
    # Wait for manager to be ready
    log_info "Waiting for manager to start..."
    sleep 5
    
    if docker ps | grep -q wifi-manager; then
        log_info "✅ Manager container started"
        
        # Check if container can access Docker socket
        log_info "Verifying Docker socket access in container..."
        if docker exec wifi-manager ls -la /var/run/docker.sock >/dev/null 2>&1; then
            log_info "✅ Docker socket file is visible in container"
            # Actually test Docker API access
            if docker exec wifi-manager python3 -c "import docker; c=docker.from_env(); c.ping()" >/dev/null 2>&1; then
                log_info "✅ Container can access Docker API"
            else
                log_warn "⚠️ Container cannot access Docker API (permission issue)"
                log_warn "   The app will run in limited mode"
                log_warn "   Try: sudo chmod 666 /var/run/docker.sock"
            fi
        else
            log_warn "⚠️ Docker socket not found in container"
            log_warn "   Check logs: docker logs wifi-manager"
        fi
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
    log_info "  • Reinstall (clean): FORCE_CLEAN_INSTALL=true curl -sSL ... | sudo bash"
    echo
    log_info "📝 Note: Old installations have been backed up if they existed"
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
    download_project_files
    build_images
    start_manager
    
    show_completion
}

main "$@"
