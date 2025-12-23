#!/usr/bin/env bash
# Fix Docker socket permissions for manager container

set -euo pipefail

echo "🔧 Fixing Docker socket permissions..."

# Check if Docker socket exists
if [[ ! -S /var/run/docker.sock ]]; then
    echo "❌ Docker socket not found at /var/run/docker.sock"
    exit 1
fi

# Get current permissions
CURRENT_PERMS=$(stat -c "%a" /var/run/docker.sock 2>/dev/null || stat -f "%OLp" /var/run/docker.sock 2>/dev/null || echo "unknown")
echo "Current Docker socket permissions: $CURRENT_PERMS"

# Check if we can access it
if docker ps >/dev/null 2>&1; then
    echo "✅ Docker socket is accessible from host"
else
    echo "⚠️ Docker socket may not be accessible"
fi

# The socket should be accessible to root, which the container runs as
# If there are still issues, it might be AppArmor or SELinux

echo ""
echo "💡 If the container still can't access Docker socket:"
echo "   1. Ensure container runs as root (user: '0:0' in docker-compose.yml)"
echo "   2. Check AppArmor: sudo aa-status | grep docker"
echo "   3. Check container logs: docker logs wifi-manager"
echo "   4. Try: sudo chmod 666 /var/run/docker.sock (temporary fix)"
