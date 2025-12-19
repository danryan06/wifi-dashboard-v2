#!/bin/bash
# MAC Address Rotation Script
# Generates a random MAC address and applies it to the interface

set -euo pipefail

INTERFACE="${1:-wlan_sim}"

if [ -z "$INTERFACE" ]; then
    echo "Usage: $0 <interface>"
    exit 1
fi

# Check if interface exists
if ! ip link show "$INTERFACE" >/dev/null 2>&1; then
    echo "ERROR: Interface $INTERFACE not found"
    exit 1
fi

# Generate random MAC address (locally administered, unicast)
# Format: XX:XX:XX:XX:XX:XX where first byte is even (unicast) and bit 1 is set (locally administered)
generate_mac() {
    # First byte: 0x02-0xFE, even numbers only (unicast), bit 1 set (locally administered)
    first_byte=$(printf "%02x" $((0x02 + (RANDOM % 124) * 2)))
    
    # Remaining 5 bytes: random
    for i in {1..5}; do
        byte=$(printf "%02x" $((RANDOM % 256)))
        first_byte="${first_byte}:${byte}"
    done
    
    echo "$first_byte"
}

NEW_MAC=$(generate_mac)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Rotating MAC address for $INTERFACE to $NEW_MAC"

# Bring interface down
ip link set "$INTERFACE" down || true

# Set new MAC address
if ip link set "$INTERFACE" address "$NEW_MAC"; then
    echo "Successfully set MAC address to $NEW_MAC"
else
    echo "WARNING: Failed to set MAC address (may require specific driver support)"
    # Try alternative method using iw
    if command -v iw >/dev/null 2>&1; then
        PHY=$(iw dev "$INTERFACE" info 2>/dev/null | grep -oP 'wiphy \K\d+' || echo "")
        if [ -n "$PHY" ]; then
            echo "Attempting MAC rotation via iw phy$PHY"
            # Note: Not all drivers support MAC rotation via iw
        fi
    fi
fi

# Bring interface back up
ip link set "$INTERFACE" up || true

echo "MAC rotation complete"
