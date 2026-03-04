#!/bin/bash
# Good Wi-Fi Client Persona
# Connects successfully, generates traffic, supports roaming

set -euo pipefail

INTERFACE="$1"
SSID="$2"
PASSWORD="$3"
TRAFFIC_INTENSITY="${4:-medium}"
ROAMING_ENABLED="${5:-false}"
ROAMING_PROFILE="${6:-standard}"

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/persona-good-${INTERFACE}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GOOD-CLIENT: $*" | tee -a "$LOG_FILE"
}

log "Starting good Wi-Fi client on $INTERFACE"
log "SSID: $SSID, Traffic: $TRAFFIC_INTENSITY, Roaming: $ROAMING_ENABLED, Profile: $ROAMING_PROFILE"

# Roaming profile tuning.
case "$ROAMING_PROFILE" in
    aggressive)
        ROAM_SCAN_INTERVAL=30
        ROAM_MIN_IMPROVEMENT_DB=5
        ROAM_MIN_SIGNAL_DBM=-82
        ;;
    *)
        ROAM_SCAN_INTERVAL=90
        ROAM_MIN_IMPROVEMENT_DB=8
        ROAM_MIN_SIGNAL_DBM=-78
        ;;
esac

# More stable connection check than a single `iw link` sample.
is_connected() {
    # Prefer wpa_cli state when available.
    if command -v wpa_cli >/dev/null 2>&1; then
        local state
        state=$(wpa_cli -i "$INTERFACE" status 2>/dev/null | grep "^wpa_state=" | cut -d= -f2 || true)
        if [ "$state" = "COMPLETED" ]; then
            return 0
        fi
    fi

    # Fallback to iw link output.
    iw dev "$INTERFACE" link 2>/dev/null | grep -qE "Connected|SSID"
}

is_integer() {
    [ -n "${1:-}" ] && [ "$1" -eq "$1" ] 2>/dev/null
}

get_current_bssid() {
    if command -v wpa_cli >/dev/null 2>&1; then
        wpa_cli -i "$INTERFACE" status 2>/dev/null | awk -F= '/^bssid=/{print $2; exit}'
    fi
}

get_current_signal_dbm() {
    local sig
    sig=$(iw dev "$INTERFACE" link 2>/dev/null | awk '/signal:/ {print $2; exit}')
    if is_integer "$sig"; then
        echo "$sig"
        return 0
    fi

    if command -v wpa_cli >/dev/null 2>&1; then
        sig=$(wpa_cli -i "$INTERFACE" signal_poll 2>/dev/null | awk -F= '/^RSSI=/{print $2; exit}')
        if is_integer "$sig"; then
            echo "$sig"
            return 0
        fi
    fi

    return 1
}

discover_best_bssid_wpa() {
    local current_bssid="$1"
    local best

    # Trigger a scan; scan_results may still include previous scans if this fails.
    wpa_cli -i "$INTERFACE" scan >/dev/null 2>&1 || true
    sleep 2

    best=$(
        wpa_cli -i "$INTERFACE" scan_results 2>/dev/null \
            | awk -F'\t' -v target_ssid="$SSID" -v current="$current_bssid" '
                NR > 2 && $5 == target_ssid && tolower($1) != tolower(current) {
                    print $1 "|" $3
                }
            ' \
            | sort -t'|' -k2,2nr \
            | head -1
    )

    [ -n "$best" ] || return 1
    echo "$best"
    return 0
}

discover_best_bssid_iw() {
    local current_bssid="$1"
    local scan_output
    local best
    local attempt

    for attempt in 1 2 3; do
        scan_output=$(iw dev "$INTERFACE" scan 2>&1) && break
        if echo "$scan_output" | grep -qi "busy"; then
            log "iw scan busy (attempt ${attempt}/3), retrying..."
            sleep 2
            continue
        fi
        return 1
    done

    [ -n "${scan_output:-}" ] || return 1

    best=$(
        echo "$scan_output" \
            | awk -v target_ssid="$SSID" -v current="$current_bssid" '
                /^BSS / {
                    bssid=$2
                    sub(/\(.*/, "", bssid)
                    signal=""
                    ssid=""
                }
                /^[[:space:]]*signal:/ {
                    signal=int($2)
                }
                /^[[:space:]]*SSID:/ {
                    ssid=substr($0, index($0, $2))
                    if (ssid == target_ssid && tolower(bssid) != tolower(current) && signal != "") {
                        print bssid "|" signal
                    }
                }
            ' \
            | sort -t'|' -k2,2nr \
            | head -1
    )

    [ -n "$best" ] || return 1
    echo "$best"
    return 0
}

discover_best_bssid() {
    local current_bssid="$1"

    command -v wpa_cli >/dev/null 2>&1 || return 1

    # Fast path: use wpa_cli scan cache first.
    if best=$(discover_best_bssid_wpa "$current_bssid"); then
        echo "$best"
        return 0
    fi

    # Fallback: full iw scan for complete BSSID view.
    if best=$(discover_best_bssid_iw "$current_bssid"); then
        log "Using iw scan fallback candidate list"
        echo "$best"
        return 0
    fi

    return 1
}

perform_roam() {
    local target_bssid="$1"
    local roam_timeout=20
    local waited=0

    log "Attempting roam to BSSID $target_bssid"
    if ! wpa_cli -i "$INTERFACE" roam "$target_bssid" >/dev/null 2>&1; then
        log "Roam command failed for $target_bssid"
        return 1
    fi

    while [ "$waited" -lt "$roam_timeout" ]; do
        local state
        local bssid
        state=$(wpa_cli -i "$INTERFACE" status 2>/dev/null | awk -F= '/^wpa_state=/{print $2; exit}')
        bssid=$(wpa_cli -i "$INTERFACE" status 2>/dev/null | awk -F= '/^bssid=/{print $2; exit}')

        if [ "$state" = "COMPLETED" ] && [ "$bssid" = "$target_bssid" ]; then
            log "Roam successful: now on $bssid"
            return 0
        fi

        sleep 1
        waited=$((waited + 1))
    done

    log "Roam timeout for target $target_bssid; forcing reconnect"
    wpa_cli -i "$INTERFACE" reconnect >/dev/null 2>&1 || true
    return 1
}

# Connect to Wi-Fi using wpa_supplicant
connect_wifi() {
    log "Connecting to SSID: $SSID"
    
    # Ensure interface is up and ready
    ip link set "$INTERFACE" up 2>/dev/null || true
    # Realtek USB adapters are often unstable with power save enabled.
    iw dev "$INTERFACE" set power_save off 2>/dev/null || true
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
    # Keep key_mgmt broadly compatible across wpa_supplicant versions.
    # Some builds reject FT-PSK token parsing in this field.
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
    log "Starting wpa_supplicant..."
    if wpa_supplicant -B -Dnl80211 -i "$INTERFACE" -c "$WPA_CONF" -dd >> "$LOG_FILE" 2>&1; then
        log "wpa_supplicant started successfully"
        sleep 2  # Give wpa_supplicant time to initialize
        
        # Use wpa_cli to actively connect (more reliable than waiting)
        if command -v wpa_cli >/dev/null 2>&1; then
            log "Triggering connection via wpa_cli..."
            wpa_cli -i "$INTERFACE" reconnect 2>&1 | tee -a "$LOG_FILE" || true
            wpa_cli -i "$INTERFACE" select_network 0 2>&1 | tee -a "$LOG_FILE" || true
        fi
    else
        log "ERROR: Failed to start wpa_supplicant"
        # Check for common errors
        if [ ! -f "$WPA_CONF" ]; then
            log "ERROR: wpa_supplicant config file not found: $WPA_CONF"
        fi
        if ! iw dev "$INTERFACE" info >/dev/null 2>&1; then
            log "ERROR: Interface $INTERFACE not found or not accessible"
            iw dev "$INTERFACE" info 2>&1 | tee -a "$LOG_FILE" || true
        fi
        # Show last few lines of log for debugging
        log "Last 10 lines of wpa_supplicant output:"
        tail -10 "$LOG_FILE" | tee -a "$LOG_FILE" || true
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
            wpa_state=$(echo "$wpa_status" | grep "^wpa_state=" | cut -d= -f2)
            
            # Log wpa_cli status every 5 seconds for debugging
            if [ $((wait_count % 5)) -eq 0 ] || [ "$wpa_state" != "COMPLETED" ]; then
                log "wpa_cli status: wpa_state=$wpa_state, $(echo "$wpa_status" | grep -E "ssid|bssid|ip_address|address" | tr '\n' ' ')"
            fi
            
            if [ "$wpa_state" = "COMPLETED" ]; then
                connected=true
                log "Connection confirmed via wpa_cli (wpa_state=COMPLETED)"
            elif [ "$wpa_state" = "ASSOCIATING" ] || [ "$wpa_state" = "ASSOCIATED" ] || [ "$wpa_state" = "4WAY_HANDSHAKE" ]; then
                log "Connection in progress: wpa_state=$wpa_state"
            elif [ "$wpa_state" = "DISCONNECTED" ] || [ "$wpa_state" = "SCANNING" ]; then
                # Try to trigger connection again
                if [ $((wait_count % 10)) -eq 0 ]; then
                    log "Still disconnected, triggering reconnect..."
                    wpa_cli -i "$INTERFACE" reconnect 2>&1 | tee -a "$LOG_FILE" || true
                fi
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
            log "=== Connection Failure Debug Info ==="
            log "Interface status:"
            iw dev "$INTERFACE" link 2>&1 | tee -a "$LOG_FILE" || log "iw dev failed"
            log "Interface info:"
            iw dev "$INTERFACE" info 2>&1 | tee -a "$LOG_FILE" || true
            if command -v wpa_cli >/dev/null 2>&1; then
                log "wpa_cli full status:"
                wpa_cli -i "$INTERFACE" status 2>&1 | tee -a "$LOG_FILE" || true
                log "wpa_cli scan results:"
                wpa_cli -i "$INTERFACE" scan_results 2>&1 | head -20 | tee -a "$LOG_FILE" || true
            fi
            log "Interface IP info:"
            ip addr show "$INTERFACE" 2>&1 | tee -a "$LOG_FILE" || true
            log "Last 30 lines of wpa_supplicant debug output:"
            tail -30 "$LOG_FILE" | grep -E "wpa_supplicant|CTRL|WPA|auth|assoc|4-way|EAPOL" | tail -20 | tee -a "$LOG_FILE" || true
            log "=== End Debug Info ==="
            return 1
        fi
        sleep 1
        wait_count=$((wait_count + 1))
    done
    
    log "Successfully connected to $SSID"
    
    # Request DHCP
    log "Requesting DHCP lease"
    # Clean up any stale dhcpcd state for this interface before requesting a lease.
    dhcpcd -x "$INTERFACE" 2>/dev/null || true
    timeout 30 dhcpcd -w "$INTERFACE" || log "WARNING: DHCP may have failed"
    
    sleep 3
    
    # Verify connectivity (bind ping to the target interface).
    if ping -I "$INTERFACE" -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
        log "Internet connectivity verified"
        return 0
    else
        # Keep session up even if internet probe fails once; Wi-Fi is associated and has DHCP.
        # Traffic generator + monitor loop will continue and recover naturally.
        log "WARNING: No internet connectivity (association is up, continuing)"
        return 0
    fi
}

roam_bssids() {
    if [ "$ROAMING_ENABLED" != "true" ]; then
        return
    fi
    
    log "Roaming enabled - active BSSID scanning started (interval=${ROAM_SCAN_INTERVAL}s, min_gain=${ROAM_MIN_IMPROVEMENT_DB}dB)"
    
    while true; do
        sleep "$ROAM_SCAN_INTERVAL"

        if ! is_connected; then
            log "Roaming check skipped: interface not connected"
            continue
        fi

        current_bssid=$(get_current_bssid || true)
        current_signal=$(get_current_signal_dbm || true)

        if [ -z "$current_bssid" ]; then
            log "Roaming check skipped: current BSSID unknown"
            continue
        fi

        if ! is_integer "$current_signal"; then
            current_signal=-100
        fi

        candidate=$(discover_best_bssid "$current_bssid" || true)
        if [ -z "$candidate" ]; then
            log "No alternate BSSID candidates found for SSID $SSID"
            continue
        fi

        target_bssid="${candidate%%|*}"
        target_signal="${candidate##*|}"

        if ! is_integer "$target_signal"; then
            log "Skipping candidate $target_bssid due to invalid signal value: $target_signal"
            continue
        fi

        signal_gain=$((target_signal - current_signal))

        if [ "$target_signal" -lt "$ROAM_MIN_SIGNAL_DBM" ]; then
            log "Skipping candidate $target_bssid (signal=${target_signal}dBm below floor ${ROAM_MIN_SIGNAL_DBM}dBm)"
            continue
        fi

        if [ "$signal_gain" -lt "$ROAM_MIN_IMPROVEMENT_DB" ]; then
            log "Keeping current BSSID $current_bssid (current=${current_signal}dBm, candidate=${target_signal}dBm, gain=${signal_gain}dB < ${ROAM_MIN_IMPROVEMENT_DB}dB)"
            continue
        fi

        log "Roam candidate selected: $target_bssid (current=${current_signal}dBm, target=${target_signal}dBm, gain=${signal_gain}dB)"
        perform_roam "$target_bssid" || true
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
        
        # Monitor connection with tolerance for transient link sampling glitches.
        missed_checks=0
        while true; do
            if is_connected; then
                missed_checks=0
            else
                missed_checks=$((missed_checks + 1))
                log "Connection check missed ($missed_checks/6)"
                if [ "$missed_checks" -ge 6 ]; then
                    break
                fi
            fi
            sleep 5
        done
        
        log "Connection lost, reconnecting..."
        kill $TRAFFIC_PID 2>/dev/null || true
        [ -n "${ROAMING_PID:-}" ] && kill $ROAMING_PID 2>/dev/null || true
    else
        log "Connection failed, retrying in 10s..."
        sleep 10
    fi
done
