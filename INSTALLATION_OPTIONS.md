# Installation Options

## Standard Installation

```bash
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

This will:
- Install Docker and Docker Compose (if needed)
- Clean up old v1 systemd services
- Stop any existing v2 containers
- Download project files
- Build Docker images
- Start the manager container

## Force Clean Installation

If you want to completely remove an existing v2 installation and start fresh:

```bash
FORCE_CLEAN_INSTALL=true curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

This will:
- Backup existing v2 installation directory
- Remove all existing containers and images
- Perform a fresh installation

## Clean Docker Images

To remove old Docker images before installing:

```bash
CLEAN_DOCKER_IMAGES=true curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

## Upgrade from v1

The installer automatically:
- Stops all v1 systemd services
- Disables v1 services
- Backs up the old v1 directory to `wifi_test_dashboard.backup.<timestamp>`
- Cleans up service files
- Installs v2 alongside (different directory)

## Upgrade Existing v2

The installer automatically:
- Stops existing manager container
- Stops all persona containers
- Downloads updated files
- Rebuilds images
- Restarts manager

Your existing configuration and state files are preserved.

## Manual Cleanup

If you need to manually clean up:

```bash
# Stop all containers
docker stop wifi-manager $(docker ps -q --filter "name=persona-") 2>/dev/null
docker rm wifi-manager $(docker ps -aq --filter "name=persona-") 2>/dev/null

# Remove images (optional)
docker rmi wifi-dashboard-manager:latest wifi-dashboard-persona:latest 2>/dev/null

# Remove directory (optional - backs up first)
mv /home/pi/wifi_dashboard_v2 /home/pi/wifi_dashboard_v2.backup.$(date +%s)
```
