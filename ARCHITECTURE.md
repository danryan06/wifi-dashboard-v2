# Architecture Overview - Wi-Fi Dashboard v2.0

## Manager-Worker Container Architecture

This document describes the containerized architecture of Wi-Fi Dashboard v2.0.

## Core Components

### 1. Manager Container (`wifi-manager`)

**Purpose**: Orchestrates persona containers and manages the dashboard UI.

**Key Responsibilities**:
- Flask web dashboard (port 5000)
- Docker API integration for container lifecycle
- Interface namespace management
- State persistence
- Log aggregation

**Configuration**:
- Runs with `--privileged` and `--pid host` for interface operations
- Mounts Docker socket for container management
- Mounts `/lib/modules` for Wi-Fi driver access

**Files**:
- `manager/app.py` - Flask application
- `manager/manager_logic.py` - Persona lifecycle management
- `manager/interface_manager.py` - Interface namespace operations

### 2. Persona Containers

**Purpose**: Isolated client simulations with dedicated network interfaces.

**Types**:
- **Good Client**: Successful Wi-Fi authentication with traffic generation
- **Bad Client**: Authentication failures for security testing
- **Wired Client**: Ethernet-based heavy traffic

**Key Features**:
- Lightweight Alpine-based images
- Isolated network namespaces
- MAC address rotation
- Traffic generation scripts
- Wi-Fi connection management

**Files**:
- `persona/entrypoint.sh` - Container entrypoint
- `persona/good_client.sh` - Good client logic
- `persona/bad_client.sh` - Bad client logic
- `persona/wired_client.sh` - Wired client logic
- `persona/rotate_mac.sh` - MAC rotation

## Interface Management Flow

### The "Lift & Shift" Mechanism

1. **Detection**: Manager scans for available physical interfaces (`wlan0`, `wlan1`, etc.)

2. **Container Creation**: Manager creates persona container with:
   - `network_mode: none` (no default network)
   - `pid_mode: host` (access to host PID namespace)
   - `privileged: true` (required for Wi-Fi operations)

3. **Interface Movement**: 
   ```bash
   # Get container PID
   pid=$(docker inspect <container> | jq '.[0].State.Pid')
   
   # Get PHY name
   phy=$(iw dev wlan1 info | grep wiphy | awk '{print $2}')
   
   # Move interface into container namespace
   iw phy $phy set netns $pid
   
   # Rename inside container
   nsenter -t $pid -n ip link set wlan1 name wlan_sim
   nsenter -t $pid -n ip link set wlan_sim up
   ```

4. **Standardization**: Interface always appears as `wlan_sim` inside container

5. **Cleanup**: On container stop:
   ```bash
   # Return interface to host namespace (PID 1)
   nsenter -t $pid -n ip link set wlan_sim netns 1
   ```

## State Management

### Persistence

State is stored in `/app/state/personas.json`:

```json
{
  "personas": {
    "container_id": {
      "container_name": "persona-good-wlan1-1234567890",
      "persona_type": "good",
      "interface": "wlan1",
      "hostname": "CNXNMist-WiFiGood",
      "created_at": "2024-01-01T12:00:00",
      "status": "running"
    }
  },
  "interfaces": {
    "wlan1": {
      "container_id": "...",
      "container_name": "...",
      "persona_type": "good",
      "assigned_at": "2024-01-01T12:00:00"
    }
  },
  "last_updated": "2024-01-01T12:00:00"
}
```

### Recovery

On reboot, the Manager can restore personas from state (requires SSID/password from config file).

## Networking Model

### Host Network Access

- Manager uses `network_mode: host` for direct interface access
- Persona containers use `network_mode: none` and receive interfaces via namespace movement

### Interface Isolation

Each persona container has:
- Its own network namespace
- Dedicated physical interface
- Isolated traffic generation
- Independent MAC address

## Scalability

### Multiple USB NICs

The architecture supports 4+ USB Wi-Fi adapters:

1. Each adapter appears as `wlan0`, `wlan1`, `wlan2`, `wlan3`, etc.
2. Manager detects all available interfaces
3. User assigns personas to interfaces via UI
4. Each persona gets its own container and interface

### PoE+ Power

- USB adapters can be powered via PoE+ splitters
- No special configuration needed
- Standard USB power requirements apply

## Security Considerations

### Container Isolation

- Persona containers run in isolated namespaces
- No network access except via assigned interface
- MAC rotation prevents device fingerprinting

### Privileged Access

- Manager requires `--privileged` for interface operations
- Persona containers require `--privileged` for Wi-Fi operations
- Both run on trusted host (Raspberry Pi)

## Logging

### Centralized Logs

- Manager aggregates logs from all persona containers
- Logs streamed to UI via Docker API
- Persistent logs in `/app/logs/`

### Log Sources

- Manager logs: `manager.log`
- Persona logs: `persona-{type}-{interface}.log`
- Traffic logs: `traffic-{interface}.log`

## API Design

### REST Endpoints

- `GET /api/personas` - List all personas
- `POST /api/personas` - Start new persona
- `DELETE /api/personas/<id>` - Stop persona
- `GET /api/personas/<id>/logs` - Get persona logs
- `GET /api/interfaces` - List available interfaces

### Request/Response Format

```json
// Start persona
POST /api/personas
{
  "persona_type": "good",
  "interface": "wlan1",
  "ssid": "YourSSID",
  "password": "YourPassword"
}

// Response
{
  "success": true,
  "message": "Persona good started on wlan1",
  "container_id": "..."
}
```

## Deployment

### Docker Compose

```yaml
services:
  manager:
    build:
      dockerfile: Dockerfile.manager
    privileged: true
    network_mode: host
    pid: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /lib/modules:/lib/modules:ro
```

### One-Line Install

```bash
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

## Future Enhancements

- Kubernetes deployment option
- Prometheus metrics integration
- Grafana dashboards
- Multi-host persona distribution
- Advanced roaming algorithms
- BSSID discovery and management
