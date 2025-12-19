# Quick Start Guide - Wi-Fi Dashboard v2.0

## Installation

### One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

This will:
1. Install Docker and Docker Compose (if needed)
2. Clean up any old v1 installations
3. Build Docker images
4. Start the Manager container
5. Set up directory structure

## First Run

1. **Access Dashboard**: Open `http://<your-pi-ip>:5000` in your browser

2. **Configure Wi-Fi**:
   - Go to "Wi-Fi Config" tab
   - Enter your SSID and password
   - Click "Save Configuration"

3. **Start Your First Persona**:
   - Go to "Personas" tab
   - Select persona type (Good/Bad/Wired)
   - Select an available interface
   - Click "Start Persona"

4. **Monitor**:
   - View status in "Status" tab
   - Check logs in "Logs" tab
   - See hardware assignments in "Hardware" tab

## Common Commands

```bash
# View manager logs
docker logs wifi-manager -f

# List running personas
docker ps | grep persona

# Stop all personas
curl -X POST http://localhost:5000/shutdown

# Restart manager
docker-compose -f /home/pi/wifi_dashboard_v2/docker-compose.yml restart manager
```

## Troubleshooting

### Manager won't start
```bash
# Check Docker is running
sudo systemctl status docker

# View manager logs
docker logs wifi-manager

# Rebuild images
cd /home/pi/wifi_dashboard_v2
docker-compose build
```

### Interface not moving to container
- Ensure container has `--privileged` flag
- Check interface exists: `ip link show wlan1`
- Verify manager has Docker socket access
- Check manager logs for errors

### Persona container crashes
```bash
# View persona logs
docker logs <container-id>

# Check interface inside container
docker exec <container-id> ip link show
```

## Architecture Overview

- **Manager Container**: Dashboard UI + API (port 5000)
- **Persona Containers**: Isolated client simulations
- **Interface Movement**: Physical NICs moved into container namespaces
- **State Persistence**: Survives reboots

## Next Steps

- Read [README.md](README.md) for full documentation
- See [ARCHITECTURE.md](ARCHITECTURE.md) for technical details
- Check [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for feature status
