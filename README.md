# Wi-Fi Test Dashboard v2.0

🌐 **Containerized Manager-Worker Architecture for Juniper Mist PoC Demonstrations**

A scalable, containerized network testing platform that simulates realistic client behavior with support for 4+ USB NICs powered by PoE+. This version refactors the original host-based architecture into a Docker-based "Manager-Worker" model.

## 🆕 What's New in v2.0

### 🐳 **Containerized Architecture**
- **Manager-Worker Model**: Dashboard runs as Manager container, personas as Worker containers
- **Interface Namespace Management**: Physical NICs are moved into container namespaces dynamically
- **Scalability**: Support for 4+ USB Wi-Fi adapters with PoE+ power
- **Isolation**: Each persona runs in its own container with isolated networking
- **Portability**: Runs on any Docker host, not just Raspberry Pi

### 🔧 **Key Features**
- **Dynamic Interface Assignment**: Hot-plug physical interfaces into persona containers
- **MAC Rotation**: Automatic MAC address rotation per persona
- **Traffic Generation**: Same powerful traffic generation as v1, now containerized
- **Wi-Fi Roaming**: Support for BSSID roaming (when enabled)
- **Log Aggregation**: Centralized logging from all persona containers
- **State Persistence**: Survives reboots with state restoration

## 📋 Requirements

### Hardware
- Raspberry Pi 4 (recommended) or any Docker-capable Linux host
- **4+ USB Wi-Fi adapters** (for full scalability demonstration)
- PoE+ power supply (for powering multiple USB adapters)
- Ethernet connection for wired testing
- **Multiple APs broadcasting the same SSID** (for roaming)

### Software
- Docker 20.10+
- Docker Compose 2.0+
- Linux kernel with network namespace support
- Root/sudo access

## 🚀 Installation

### Quick Install (One-Line)

```bash
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

This will:
- Install Docker and Docker Compose (if not present)
- Clean up any old systemd-based installations
- Build Docker images (Manager and Persona)
- Start the Manager container
- Set up directory structure

### Manual Installation

1. Clone the repository:
```bash
git clone https://github.com/danryan06/wifi-dashboard-v2.git
cd wifi-dashboard-v2
```

2. Run the setup script:
```bash
sudo ./setup.sh
```

## 🎯 Usage

### 1. Access the Dashboard

Open your web browser and navigate to:
```
http://[PI_IP_ADDRESS]:5000
```

### 2. Configure Wi-Fi Settings

1. Go to the **Wi-Fi Config** tab
2. Enter your target SSID and password
3. Click **Save Configuration**

### 3. Start Personas

1. Navigate to the **Personas** tab
2. Select an available interface (e.g., `wlan1`)
3. Choose persona type:
   - **Good Client**: Successful authentication with traffic generation
   - **Bad Client**: Authentication failures for security testing
   - **Wired Client**: Ethernet-based heavy traffic
4. Click **Start Persona**

The Manager will:
- Create a persona container
- Move the physical interface into the container's namespace
- Start traffic generation
- Begin Wi-Fi connection (for Wi-Fi personas)

### 4. Monitor Activity

- **Status Tab**: Real-time system information and persona status
- **Personas Tab**: View all running persona containers
- **Logs Tab**: View aggregated logs from all personas
- **Interfaces Tab**: See available physical interfaces

## 🏗️ Architecture

### Manager Container
- Flask web dashboard (port 5000)
- Docker API integration
- Interface namespace management
- Persona lifecycle orchestration
- State persistence

### Persona Containers
- Lightweight Alpine-based images
- Isolated network namespaces
- Traffic generation scripts
- Wi-Fi connection management
- MAC address rotation

### Interface Management
The core "lift & shift" mechanism:

1. **Physical Interface Detection**: Manager scans for available Wi-Fi interfaces
2. **Container Creation**: Manager creates persona container with host PID namespace
3. **Interface Movement**: Physical interface moved into container namespace using `iw phy set netns`
4. **Standardization**: Interface renamed to `wlan_sim` inside container
5. **Cleanup**: On container stop, interface returned to host namespace

## 📊 API Endpoints

### Persona Management
- `GET /api/personas` - List all persona containers
- `POST /api/personas` - Start a new persona
  ```json
  {
    "persona_type": "good",
    "interface": "wlan1",
    "ssid": "YourSSID",
    "password": "YourPassword"
  }
  ```
- `DELETE /api/personas/<container_id>` - Stop a persona
- `GET /api/personas/<container_id>/logs` - Get persona logs

### Interface Management
- `GET /api/interfaces` - List available physical interfaces

## 🔧 Configuration

### Environment Variables (Persona Containers)

- `PERSONA_TYPE`: Type of persona (`good`, `bad`, `wired`)
- `INTERFACE`: Interface name inside container (always `wlan_sim`)
- `HOSTNAME`: DHCP hostname (e.g., `CNXNMist-WiFiGood`)
- `SSID`: Wi-Fi network SSID
- `PASSWORD`: Wi-Fi password
- `TRAFFIC_INTENSITY`: Traffic level (`light`, `medium`, `heavy`)
- `ROAMING_ENABLED`: Enable Wi-Fi roaming (`true`/`false`)

### State Persistence

State is persisted in `/app/state/personas.json`:
- Container IDs and names
- Interface assignments
- Persona configurations
- Timestamps

On reboot, the Manager can restore personas (requires SSID/password from config).

## 🛠️ Development

### Building Images

```bash
# Build persona image
docker build -f Dockerfile.persona -t wifi-dashboard-persona:latest .

# Build manager image
docker build -f Dockerfile.manager -t wifi-dashboard-manager:latest .
```

### Running Locally

```bash
# Start manager
docker-compose up -d manager

# View logs
docker logs wifi-manager -f

# Stop all
docker-compose down
```

## 🔍 Troubleshooting

### Interface Not Moving to Container

1. Check container is running: `docker ps`
2. Verify container has host PID namespace: `docker inspect <container> | grep PidMode`
3. Check interface exists: `ip link show wlan1`
4. View manager logs: `docker logs wifi-manager`

### Persona Container Crashes

1. Check persona logs: `docker logs <container_id>`
2. Verify interface is available: `ip link show wlan_sim` (inside container)
3. Check Wi-Fi credentials are correct
4. Ensure interface driver supports namespace movement

### Manager Can't Access Docker Socket

1. Verify Docker socket is mounted: `docker exec wifi-manager ls -la /var/run/docker.sock`
2. Check manager has proper permissions
3. Restart manager: `docker-compose restart manager`

## 📝 Migration from v1

If you have v1 installed:

1. The setup script automatically cleans up old systemd services
2. Old installation is preserved (not deleted, just stopped)
3. You can run both versions side-by-side (on different ports)
4. v2 uses different directory: `/home/pi/wifi_dashboard_v2`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Test with multiple USB Wi-Fi adapters
4. Commit changes: `git commit -am 'Add feature'`
5. Push to branch: `git push origin feature-name`
6. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🔗 Links

- **Repository**: https://github.com/danryan06/wifi-dashboard-v2
- **Issues**: https://github.com/danryan06/wifi-dashboard-v2/issues
- **v1 Repository** (for reference): https://github.com/danryan06/wifi-dashboard

## 🙏 Acknowledgments

This v2 architecture builds upon the solid foundation of v1, refactoring it into a scalable containerized model suitable for demonstrations with multiple Wi-Fi adapters.

---

**Version**: 2.0.0  
**Last Updated**: 2024
