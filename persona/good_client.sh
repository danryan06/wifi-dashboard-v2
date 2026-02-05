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
    
    # Ensure interface is up and ready
    ip link set "$INTERFACE" up 2>/dev/null || true
    sleep 1
    
    # Scan for networks to ensure interface is working
    log "Scanning for networks..."
    if iw dev "$INTERFACE" scan >/dev/null 2>&1; then
        log "Scan successful, interface is ready"
    else
        log "WARNING: Scan failed, but continuing..."
    fi
    
    # Create wpa_supplicant config
    WPA_CONF="/tmp/wpa_supplicant_${INTERFACE}.conf"
    cat > "$WPA_CONF" <<EOF
ctrl_interface=/var/run/wpa_supplicant
ctrl_interface_group=0
update_config=1

network={
    ssid="$SSID"
    psk="$PASSWORD"
    key_mgmt=WPA-PSK
    scan_ssid=1
}
EOF
    chmod 600 "$WPA_CONF"
    log "Created wpa_supplicant config: $WPA_CONF"
    
    # Kill any existing wpa_supplicant for this interface
    pkill -f "wpa_supplicant.*$INTERFACE" || true
    sleep 1
    
    # Ensure ctrl_interface directory exists
    mkdir -p /var/run/wpa_supplicant
    chmod 755 /var/run/wpa_supplicant
    
    # Start wpa_supplicant with nl80211 driver
    # -B = background, -D = driver, -i = interface, -c = config file, -dd = debug output
    if wpa_supplicant -B -Dnl80211 -i "$INTERFACE" -c "$WPA_CONF" -dd >> "$LOG_FILE" 2>&1; then
        log "wpa_supplicant started"
    else
        log "ERROR: Failed to start wpa_supplicant"
        # Check for common errors
        if [ ! -f "$WPA_CONF" ]; then
            log "ERROR: wpa_supplicant config file not found: $WPA_CONF"
        fi
        if ! iw dev "$INTERFACE" info >/dev/null 2>&1; then
            log "ERROR: Interface $INTERFACE not found or not accessible"
        fi
        return 1
    fi
    
    # Wait for connection
    max_wait=30
    wait_count=0
    while true; do
        # Check connection status using multiple methods
        connected=false
        
        # Method 1: Check iw dev link output
        if iw dev "$INTERFACE" link 2>/dev/null | grep -qE "Connected|SSID"; then
            connected=true
        fi
        
        # Method 2: Check wpa_cli status (more reliable)
        if command -v wpa_cli >/dev/null 2>&1; then
            wpa_status=$(wpa_cli -i "$INTERFACE" status 2>/dev/null)
            if echo "$wpa_status" | grep -q "wpa_state=COMPLETED"; then
                connected=true
                log "Connection confirmed via wpa_cli"
            fi
            # Log wpa_cli status every 5 seconds for debugging
            if [ $((wait_count % 5)) -eq 0 ]; then
                log "wpa_cli status: $(echo "$wpa_status" | grep -E "wpa_state|ssid|ip_address" | tr '\n' ' ')"
            fi
        fi
        
        # Method 3: Check if we have an IP address
        if ip addr show "$INTERFACE" 2>/dev/null | grep -q "inet "; then
            connected=true
            log "IP address assigned, connection confirmed"
        fi
        
        if [ "$connected" = true ]; then
            break
        fi
        
        # Check if wpa_supplicant is still running
        if ! pgrep -f "wpa_supplicant.*$INTERFACE" >/dev/null; then
            log "ERROR: wpa_supplicant process died"
            # Check last few lines of log for errors
            tail -20 "$LOG_FILE" | grep -i "error\|fail" | tail -5 >> "$LOG_FILE" || true
            return 1
        fi
        
        if [ $wait_count -ge $max_wait ]; then
            log "ERROR: Failed to connect within ${max_wait}s"
            # Show detailed status for debugging
            log "Interface status:"
            iw dev "$INTERFACE" link 2>/dev/null >> "$LOG_FILE" || log "iw dev failed"
            if command -v wpa_cli >/dev/null 2>&1; then
                log "wpa_cli full status:"
                wpa_cli -i "$INTERFACE" status 2>/dev/null >> "$LOG_FILE" || true
            fi
            log "Interface IP info:"
            ip addr show "$INTERFACE" 2>/dev/null >> "$LOG_FILE" || true
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
