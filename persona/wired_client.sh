#!/bin/bash
# Wired Client Persona
# Generates heavy traffic on ethernet interface

set -euo pipefail

INTERFACE="$1"
TRAFFIC_INTENSITY="${2:-heavy}"

LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/persona-wired-${INTERFACE}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WIRED-CLIENT: $*" | tee -a "$LOG_FILE"
}

log "Starting wired client on $INTERFACE"
log "Traffic intensity: $TRAFFIC_INTENSITY"

# Bring interface up
ip link set "$INTERFACE" up || log "WARNING: Failed to bring interface up"

# Wait for interface
sleep 2

# Request DHCP if not already configured
if ! ip addr show "$INTERFACE" | grep -q "inet "; then
    log "Requesting DHCP lease"
    dhcpcd "$INTERFACE" || dhclient "$INTERFACE" || log "WARNING: DHCP may have failed"
    sleep 3
fi

# Verify connectivity
if ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
    log "Internet connectivity verified"
else
    log "WARNING: No internet connectivity"
fi

# Keep wired persona alive and restart traffic generator if it exits.
start_traffic_generator() {
    log "Starting traffic generation (intensity: $TRAFFIC_INTENSITY)"
    /app/scripts/traffic/interface_traffic_generator.sh "$INTERFACE" loop &
    TRAFFIC_PID=$!
}

# Final sanity check before starting background workload
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    log "ERROR: Interface $INTERFACE not found, retrying in 5s..."
    sleep 5
fi

start_traffic_generator

while true; do
    sleep 10

    # If traffic generator died, restart it instead of exiting container.
    if ! kill -0 "${TRAFFIC_PID}" >/dev/null 2>&1; then
        log "WARNING: Traffic generator exited, restarting..."
        start_traffic_generator
    fi

    # Try to keep interface healthy.
    if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
        log "WARNING: Interface $INTERFACE disappeared"
        continue
    fi
    ip link set "$INTERFACE" up >/dev/null 2>&1 || true
done
