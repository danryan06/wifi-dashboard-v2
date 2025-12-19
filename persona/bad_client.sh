#!/bin/bash
# Bad Wi-Fi Client Persona
# Generates authentication failures for security testing

set -euo pipefail

INTERFACE="$1"
SSID="$2"
TRAFFIC_INTENSITY="${3:-light}"

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/persona-bad-${INTERFACE}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] BAD-CLIENT: $*" | tee -a "$LOG_FILE"
}

log "Starting bad Wi-Fi client on $INTERFACE"
log "SSID: $SSID (will use wrong password to generate auth failures)"

# Generate authentication failures
fail_auth_loop() {
    WRONG_PASSWORDS=(
        "wrongpassword123"
        "incorrectpass"
        "badpassword"
        "test123"
        "password"
    )
    
    while true; do
        for wrong_pass in "${WRONG_PASSWORDS[@]}"; do
            log "Attempting connection with wrong password: $wrong_pass"
            
            # Create wpa_supplicant config with wrong password
            WPA_CONF="/tmp/wpa_supplicant_bad_${INTERFACE}.conf"
            cat > "$WPA_CONF" <<EOF
network={
    ssid="$SSID"
    psk="$wrong_pass"
    key_mgmt=WPA-PSK
}
EOF
            
            # Kill any existing wpa_supplicant
            pkill -f "wpa_supplicant.*$INTERFACE" || true
            sleep 1
            
            # Attempt connection (will fail)
            timeout 10 wpa_supplicant -i "$INTERFACE" -c "$WPA_CONF" -f "$LOG_FILE" 2>&1 || true
            
            # Wait a bit before next attempt
            sleep 5
        done
        
        log "Completed auth failure cycle, restarting..."
        sleep 10
    done
}

# Start auth failure loop
fail_auth_loop &

# Keep script running
wait
