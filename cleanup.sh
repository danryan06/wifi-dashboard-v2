#!/usr/bin/env bash
# Wi-Fi Dashboard v2 Cleanup Script
# Standalone script to clean up installations

set -Eeuo pipefail

PI_USER="${PI_USER:-$(getent passwd 1000 | cut -d: -f1 2>/dev/null || echo 'pi')}"
PI_HOME="/home/$PI_USER"
WORK_DIR="$PI_HOME/wifi_dashboard_v2"
OLD_DIR="$PI_HOME/wifi_test_dashboard"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (use: sudo bash cleanup.sh)"
    exit 1
fi

print_banner() {
    echo -e "${BLUE}"
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════╗
║              🧹 Wi-Fi Dashboard v2 Cleanup Script                 ║
╚══════════════════════════════════════════════════════════════════╝
EOF
    echo -e "${NC}"
}

cleanup_v2_containers() {
    log_step "Cleaning up v2 Docker containers..."
    
    if ! command -v docker >/dev/null 2>&1; then
        log_info "Docker not installed, skipping container cleanup"
        return
    fi
    
    # Stop and remove manager
    if docker ps -a --format '{{.Names}}' | grep -q '^wifi-manager$'; then
        log_info "  Stopping wifi-manager..."
        docker stop wifi-manager 2>/dev/null || true
        docker rm wifi-manager 2>/dev/null || true
    fi
    
    # Stop and remove all personas
    local persona_count
    persona_count=$(docker ps -a --format '{{.Names}}' | grep -c '^persona-' 2>/dev/null || echo "0")
    if [[ "$persona_count" -gt 0 ]]; then
        log_info "  Stopping $persona_count persona container(s)..."
        docker ps -a --format '{{.Names}}' | grep '^persona-' | while read -r container; do
            log_info "    Stopping $container..."
            docker stop "$container" 2>/dev/null || true
            docker rm "$container" 2>/dev/null || true
        done
    fi
    
    # Clean up docker-compose
    if [[ -f "$WORK_DIR/docker-compose.yml" ]]; then
        log_info "  Stopping docker-compose services..."
        cd "$WORK_DIR" && docker-compose down 2>/dev/null || true
    fi
    
    log_info "✅ v2 containers cleaned up"
}

cleanup_v1_services() {
    log_step "Cleaning up v1 systemd services..."
    
    local services=(wifi-dashboard wifi-good wifi-bad wired-test traffic-eth0 traffic-wlan0 traffic-wlan1)
    local stopped=0
    
    for service in "${services[@]}"; do
        if systemctl is-active --quiet "${service}.service" 2>/dev/null; then
            log_info "  Stopping ${service}.service..."
            systemctl stop "${service}.service" 2>/dev/null || true
            ((stopped++))
        fi
        if systemctl is-enabled --quiet "${service}.service" 2>/dev/null; then
            log_info "  Disabling ${service}.service..."
            systemctl disable "${service}.service" 2>/dev/null || true
        fi
    done
    
    # Remove service files
    local service_files
    service_files=$(find /etc/systemd/system -name "wifi-*.service" -o -name "wired-test.service" -o -name "traffic-*.service" 2>/dev/null | wc -l)
    if [[ "$service_files" -gt 0 ]]; then
        log_info "  Removing $service_files service file(s)..."
        rm -f /etc/systemd/system/wifi-*.service
        rm -f /etc/systemd/system/wired-test.service
        rm -f /etc/systemd/system/traffic-*.service
        systemctl daemon-reload 2>/dev/null || true
    fi
    
    log_info "✅ v1 services cleaned up"
}

cleanup_network_interfaces() {
    log_step "Cleaning up network interfaces..."
    
    if ! command -v nmcli >/dev/null 2>&1; then
        log_info "NetworkManager not available, skipping interface cleanup"
        return
    fi
    
    local disconnected=0
    for iface in wlan0 wlan1 wlan2 wlan3 wlan4 wlan5; do
        if nmcli device status 2>/dev/null | grep -q "^$iface.*connected"; then
            log_info "  Disconnecting $iface..."
            nmcli dev disconnect "$iface" 2>/dev/null || true
            ((disconnected++))
        fi
    done
    
    if [[ $disconnected -gt 0 ]]; then
        log_info "  Disconnected $disconnected interface(s)"
    fi
    
    log_info "✅ Network interfaces cleaned up"
}

cleanup_directories() {
    log_step "Cleaning up installation directories..."
    
    local backup_suffix=".backup.$(date +%s)"
    
    # Backup v1 directory if it exists
    if [[ -d "$OLD_DIR" ]]; then
        log_info "  Backing up v1 directory to ${OLD_DIR}${backup_suffix}..."
        mv "$OLD_DIR" "${OLD_DIR}${backup_suffix}" 2>/dev/null || true
    fi
    
    # Optionally remove v2 directory
    if [[ -d "$WORK_DIR" ]] && [[ "${REMOVE_V2_DIR:-false}" == "true" ]]; then
        log_warn "  Removing v2 directory (REMOVE_V2_DIR=true)..."
        mv "$WORK_DIR" "${WORK_DIR}${backup_suffix}" 2>/dev/null || true
    else
        log_info "  v2 directory preserved at $WORK_DIR"
        log_info "  (Set REMOVE_V2_DIR=true to remove it)"
    fi
    
    log_info "✅ Directories cleaned up"
}

cleanup_docker_images() {
    log_step "Cleaning up Docker images..."
    
    if ! command -v docker >/dev/null 2>&1; then
        log_info "Docker not installed, skipping image cleanup"
        return
    fi
    
    local removed=0
    
    if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q '^wifi-dashboard-manager:latest$'; then
        log_info "  Removing wifi-dashboard-manager:latest..."
        docker rmi wifi-dashboard-manager:latest 2>/dev/null || true
        ((removed++))
    fi
    
    if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q '^wifi-dashboard-persona:latest$'; then
        log_info "  Removing wifi-dashboard-persona:latest..."
        docker rmi wifi-dashboard-persona:latest 2>/dev/null || true
        ((removed++))
    fi
    
    if [[ $removed -gt 0 ]]; then
        log_info "  Removed $removed image(s)"
    else
        log_info "  No dashboard images found"
    fi
    
    log_info "✅ Docker images cleaned up"
}

cleanup_logs() {
    log_step "Cleaning up log files..."
    
    local log_dirs=("$WORK_DIR/logs" "$OLD_DIR/logs")
    local cleaned=0
    
    for log_dir in "${log_dirs[@]}"; do
        if [[ -d "$log_dir" ]]; then
            local log_count
            log_count=$(find "$log_dir" -type f -name "*.log" 2>/dev/null | wc -l)
            if [[ "$log_count" -gt 0 ]]; then
                log_info "  Found $log_count log file(s) in $log_dir"
                if [[ "${REMOVE_LOGS:-false}" == "true" ]]; then
                    find "$log_dir" -type f -name "*.log" -delete 2>/dev/null || true
                    ((cleaned += log_count))
                fi
            fi
        fi
    done
    
    if [[ $cleaned -gt 0 ]]; then
        log_info "  Removed $cleaned log file(s)"
    else
        log_info "  Logs preserved (Set REMOVE_LOGS=true to remove)"
    fi
    
    log_info "✅ Log cleanup completed"
}

show_summary() {
    echo
    log_info "📋 Cleanup Summary:"
    log_info "  ✅ v2 Docker containers stopped and removed"
    log_info "  ✅ v1 systemd services stopped and disabled"
    log_info "  ✅ Network interfaces disconnected"
    log_info "  ✅ Directories backed up (if they existed)"
    echo
    log_info "💡 To completely remove v2 installation:"
    log_info "   REMOVE_V2_DIR=true sudo bash cleanup.sh"
    echo
    log_info "💡 To remove Docker images:"
    log_info "   REMOVE_IMAGES=true sudo bash cleanup.sh"
    echo
    log_info "💡 To remove logs:"
    log_info "   REMOVE_LOGS=true sudo bash cleanup.sh"
    echo
}

main() {
    print_banner
    
    log_info "Starting cleanup process..."
    log_info "Target user: $PI_USER"
    echo
    
    # Ask for confirmation unless FORCE is set
    if [[ "${FORCE:-false}" != "true" ]]; then
        echo -e "${YELLOW}This will stop all dashboard services and containers.${NC}"
        echo -e "${YELLOW}Existing installations will be backed up.${NC}"
        read -p "Continue? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Cleanup cancelled"
            exit 0
        fi
    fi
    
    cleanup_v2_containers
    cleanup_v1_services
    cleanup_network_interfaces
    
    if [[ "${REMOVE_IMAGES:-false}" == "true" ]]; then
        cleanup_docker_images
    fi
    
    cleanup_directories
    
    if [[ "${REMOVE_LOGS:-false}" == "true" ]]; then
        cleanup_logs
    fi
    
    show_summary
}

main "$@"
