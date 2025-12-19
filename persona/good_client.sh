#!/bin/bash
# Good Wi-Fi Client Persona
# Connects successfully, generates traffic, supports roaming

set -euo pipefail

INTERFACE="$1"
SSID="$2"
PASSWORD="$3"
TRAFFIC_INTENSITY="${4:-medium}"
ROAMING_ENABLED="${5:-false}"

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/persona-good-${INTERFACE}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GOOD-CLIENT: $*" | tee -a "$LOG_FILE"
}

log "Starting good Wi-Fi client on $INTERFACE"
log "SSID: $SSID, Traffic: $TRAFFIC_INTENSITY, Roaming: $ROAMING_ENABLED"

# Connect to Wi-Fi using wpa_supplicant
connect_wifi() {
    log "Connecting to SSID: $SSID"
    
    # Create wpa_supplicant config
    WPA_CONF="/tmp/wpa_supplicant_${INTERFACE}.conf"
    cat > "$WPA_CONF" <<EOF
network={
    ssid="$SSID"
    psk="$PASSWORD"
    key_mgmt=WPA-PSK
}
EOF
    
    # Kill any existing wpa_supplicant for this interface
    pkill -f "wpa_supplicant.*$INTERFACE" || true
    sleep 1
    
    # Start wpa_supplicant
    if wpa_supplicant -B -i "$INTERFACE" -c "$WPA_CONF" -f "$LOG_FILE"; then
        log "wpa_supplicant started"
    else
        log "ERROR: Failed to start wpa_supplicant"
        return 1
    fi
    
    # Wait for connection
    max_wait=30
    wait_count=0
    while ! iw dev "$INTERFACE" link | grep -q "Connected"; do
        if [ $wait_count -ge $max_wait ]; then
            log "ERROR: Failed to connect within ${max_wait}s"
            return 1
        fi
        sleep 1
        wait_count=$((wait_count + 1))
    done
    
    log "Successfully connected to $SSID"
    
    # Request DHCP
    log "Requesting DHCP lease"
    dhcpcd "$INTERFACE" || dhclient "$INTERFACE" || log "WARNING: DHCP may have failed"
    
    sleep 3
    
    # Verify connectivity
    if ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
        log "Internet connectivity verified"
        return 0
    else
        log "WARNING: No internet connectivity"
        return 1
    fi
}

# Roaming logic (simplified - would need BSSID discovery in full implementation)
roam_bssids() {
    if [ "$ROAMING_ENABLED" != "true" ]; then
        return
    fi
    
    log "Roaming enabled - scanning for BSSIDs..."
    
    while true; do
        sleep 120  # Check every 2 minutes
        
        # Scan for available BSSIDs
        iw dev "$INTERFACE" scan | grep -E "SSID|BSS" | head -20 >> "$LOG_FILE" || true
        
        # In a full implementation, this would:
        # 1. Discover all BSSIDs for the SSID
        # 2. Evaluate signal strength
        # 3. Roam to a better BSSID if available
        # 4. Maintain traffic during roaming
    done
}

# Main connection loop
while true; do
    if connect_wifi; then
        log "Connected successfully"
        
        # Start traffic generation in background
        log "Starting traffic generation (intensity: $TRAFFIC_INTENSITY)"
        /app/scripts/traffic/interface_traffic_generator.sh "$INTERFACE" loop &
        TRAFFIC_PID=$!
        
        # Start roaming if enabled
        if [ "$ROAMING_ENABLED" = "true" ]; then
            roam_bssids &
            ROAMING_PID=$!
        fi
        
        # Monitor connection
        while iw dev "$INTERFACE" link | grep -q "Connected"; do
            sleep 10
        done
        
        log "Connection lost, reconnecting..."
        kill $TRAFFIC_PID 2>/dev/null || true
        [ -n "${ROAMING_PID:-}" ] && kill $ROAMING_PID 2>/dev/null || true
    else
        log "Connection failed, retrying in 10s..."
        sleep 10
    fi
done
