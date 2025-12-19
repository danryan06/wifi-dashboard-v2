#!/bin/bash
# Persona Container Entrypoint
# Handles MAC rotation, interface setup, and traffic generation

set -euo pipefail

INTERFACE="${INTERFACE:-wlan_sim}"
PERSONA_TYPE="${PERSONA_TYPE:-good}"
HOSTNAME="${HOSTNAME:-CNXNMist-Persona}"
SSID="${SSID:-}"
PASSWORD="${PASSWORD:-}"
TRAFFIC_INTENSITY="${TRAFFIC_INTENSITY:-medium}"
ROAMING_ENABLED="${ROAMING_ENABLED:-false}"

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] PERSONA[$PERSONA_TYPE]: $*" | tee -a "$LOG_DIR/persona-${PERSONA_TYPE}.log"
}

log "Starting persona container: type=$PERSONA_TYPE, interface=$INTERFACE"

# Wait for interface to be moved into container namespace
log "Waiting for interface $INTERFACE to be available..."
max_wait=30
wait_count=0
while ! ip link show "$INTERFACE" >/dev/null 2>&1; do
    if [ $wait_count -ge $max_wait ]; then
        log "ERROR: Interface $INTERFACE not found after ${max_wait}s"
        exit 1
    fi
    sleep 1
    wait_count=$((wait_count + 1))
done

log "Interface $INTERFACE found"

# Rotate MAC address if this is a Wi-Fi interface
if [[ "$INTERFACE" == wlan* ]] || [[ "$INTERFACE" == wlp* ]]; then
    log "Rotating MAC address for $INTERFACE"
    /app/persona/rotate_mac.sh "$INTERFACE" || log "WARNING: MAC rotation failed (may not be supported)"
fi

# Bring interface up
log "Bringing interface $INTERFACE up"
ip link set "$INTERFACE" up || log "WARNING: Failed to bring interface up"

# Wait for interface to be ready
sleep 2

# Run persona-specific setup
case "$PERSONA_TYPE" in
    good)
        log "Starting good Wi-Fi client persona"
        if [ -n "$SSID" ] && [ -n "$PASSWORD" ]; then
            /app/persona/good_client.sh "$INTERFACE" "$SSID" "$PASSWORD" "$TRAFFIC_INTENSITY" "$ROAMING_ENABLED" &
        else
            log "WARNING: SSID or PASSWORD not provided, skipping connection"
        fi
        ;;
    bad)
        log "Starting bad Wi-Fi client persona (auth failures)"
        if [ -n "$SSID" ]; then
            /app/persona/bad_client.sh "$INTERFACE" "$SSID" "$TRAFFIC_INTENSITY" &
        else
            log "WARNING: SSID not provided, skipping connection attempts"
        fi
        ;;
    wired)
        log "Starting wired client persona"
        /app/persona/wired_client.sh "$INTERFACE" "$TRAFFIC_INTENSITY" &
        ;;
    *)
        log "ERROR: Unknown persona type: $PERSONA_TYPE"
        exit 1
        ;;
esac

# Keep container alive
log "Persona $PERSONA_TYPE running, waiting for termination signal..."
wait
