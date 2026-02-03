# Testing Guide - Wi-Fi Dashboard v2.0

## 🎯 Testing Overview

The implementation is **complete** and ready for comprehensive testing. This guide outlines systematic testing steps to validate all functionality.

## 📋 Pre-Testing Checklist

### Hardware Requirements
- [ ] Raspberry Pi 4 (or Docker-capable Linux host)
- [ ] At least 1 USB Wi-Fi adapter (4+ recommended for full testing)
- [ ] PoE+ power supply (if using multiple USB adapters)
- [ ] Ethernet connection (for wired client testing)
- [ ] Access to Wi-Fi network with known SSID/password
- [ ] Multiple APs broadcasting same SSID (for roaming tests)

### Software Requirements
- [ ] Docker 20.10+ installed
- [ ] Docker Compose 2.0+ installed
- [ ] Root/sudo access
- [ ] Network connectivity

## 🚀 Phase 1: Installation & Basic Setup

### Test 1.1: Installation
```bash
# Run one-line installer
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash

# Verify installation
docker ps | grep wifi-manager
docker images | grep wifi-dashboard
```

**Expected Results:**
- ✅ Manager container running (`wifi-manager`)
- ✅ Manager and persona images built
- ✅ Directory structure created (`/home/pi/wifi_dashboard_v2`)

### Test 1.2: Dashboard Access
```bash
# Get Pi IP address
hostname -I

# Access dashboard (from browser or curl)
curl http://<PI_IP>:5000
```

**Expected Results:**
- ✅ Dashboard loads in browser
- ✅ All tabs visible (Status, Personas, Logs, Hardware, Wi-Fi Config)
- ✅ No JavaScript errors in browser console

### Test 1.3: Manager Container Health
```bash
# Check container status
docker inspect wifi-manager | grep -i status

# Check logs for errors
docker logs wifi-manager | grep -i error

# Verify Docker socket access
docker exec wifi-manager ls -la /var/run/docker.sock
```

**Expected Results:**
- ✅ Container status: "running"
- ✅ No critical errors in logs
- ✅ Docker socket accessible (permissions OK)

## 🔌 Phase 2: Interface Detection & Management

### Test 2.1: Interface Detection
```bash
# Check available interfaces via API
curl http://localhost:5000/api/interfaces

# Or check in dashboard UI (Hardware tab)
```

**Expected Results:**
- ✅ All physical Wi-Fi interfaces detected (`wlan0`, `wlan1`, etc.)
- ✅ Interface status shown (available/assigned)
- ✅ Interface details displayed (MAC address, driver, etc.)

### Test 2.2: Interface Movement (Single Interface)
```bash
# Start a persona via API
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "persona_type": "good",
    "interface": "wlan1",
    "ssid": "YourSSID",
    "password": "YourPassword"
  }'

# Verify interface moved to container
docker ps | grep persona
CONTAINER_ID=$(docker ps | grep persona | awk '{print $1}')
docker exec $CONTAINER_ID ip link show wlan_sim
```

**Expected Results:**
- ✅ Persona container created and running
- ✅ Interface `wlan_sim` exists inside container
- ✅ Interface is UP inside container
- ✅ Interface no longer visible on host (`ip link show wlan1` should fail or show DOWN)

### Test 2.3: Interface Cleanup
```bash
# Stop persona
CONTAINER_ID=$(docker ps | grep persona | awk '{print $1}')
curl -X DELETE http://localhost:5000/api/personas/$CONTAINER_ID

# Verify interface returned to host
ip link show wlan1
```

**Expected Results:**
- ✅ Container stopped and removed
- ✅ Interface `wlan1` visible on host again
- ✅ Interface status shows UP on host

## 👤 Phase 3: Persona Functionality

### Test 3.1: Good Client Persona
```bash
# Start good client
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "persona_type": "good",
    "interface": "wlan1",
    "ssid": "YourSSID",
    "password": "YourPassword"
  }'

# Check container logs
CONTAINER_ID=$(docker ps | grep persona-good | awk '{print $1}')
docker logs $CONTAINER_ID

# Check Wi-Fi connection inside container
docker exec $CONTAINER_ID iw dev wlan_sim link
docker exec $CONTAINER_ID ip addr show wlan_sim
```

**Expected Results:**
- ✅ Container starts successfully
- ✅ MAC address rotated (check logs)
- ✅ Wi-Fi connects to SSID
- ✅ DHCP lease obtained (IP address assigned)
- ✅ Traffic generation running
- ✅ Connection shows as "connected" in `iw dev wlan_sim link`

### Test 3.2: Bad Client Persona
```bash
# Start bad client
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "persona_type": "bad",
    "interface": "wlan2",
    "ssid": "YourSSID",
    "password": "WrongPassword"
  }'

# Monitor logs for auth failures
CONTAINER_ID=$(docker ps | grep persona-bad | awk '{print $1}')
docker logs $CONTAINER_ID -f
```

**Expected Results:**
- ✅ Container starts successfully
- ✅ Authentication failures occur (check logs)
- ✅ Connection attempts repeated
- ✅ No IP address assigned (DHCP fails)

### Test 3.3: Wired Client Persona
```bash
# Start wired client (requires ethernet interface)
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "persona_type": "wired",
    "interface": "eth0"
  }'

# Check traffic generation
CONTAINER_ID=$(docker ps | grep persona-wired | awk '{print $1}')
docker exec $CONTAINER_ID ps aux | grep traffic
```

**Expected Results:**
- ✅ Container starts successfully
- ✅ Traffic generation running
- ✅ High traffic volume on ethernet interface

## 🔄 Phase 4: MAC Rotation

### Test 4.1: MAC Address Rotation
```bash
# Start persona
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{
    "persona_type": "good",
    "interface": "wlan1",
    "ssid": "YourSSID",
    "password": "YourPassword"
  }'

# Get initial MAC
CONTAINER_ID=$(docker ps | grep persona-good | awk '{print $1}')
INITIAL_MAC=$(docker exec $CONTAINER_ID cat /sys/class/net/wlan_sim/address)
echo "Initial MAC: $INITIAL_MAC"

# Wait for rotation (check rotate_mac.sh interval)
sleep 65

# Check new MAC
NEW_MAC=$(docker exec $CONTAINER_ID cat /sys/class/net/wlan_sim/address)
echo "New MAC: $NEW_MAC"
```

**Expected Results:**
- ✅ Initial MAC address set (locally administered)
- ✅ MAC address changes after rotation interval
- ✅ MAC is locally administered (second hex digit is 2, 6, A, or E)
- ✅ Wi-Fi connection maintained during rotation

## 📊 Phase 5: State Persistence

### Test 5.1: State File Creation
```bash
# Start multiple personas
# ... (start 2-3 personas)

# Check state file
cat /home/pi/wifi_dashboard_v2/state/personas.json
```

**Expected Results:**
- ✅ State file exists
- ✅ All running personas recorded
- ✅ Interface assignments tracked
- ✅ Timestamps present

### Test 5.2: Reboot Recovery
```bash
# Start personas
# ... (start 2 personas)

# Reboot system
sudo reboot

# After reboot, check if manager restores state
docker logs wifi-manager | grep -i restore
curl http://localhost:5000/api/personas
```

**Expected Results:**
- ✅ Manager starts on boot
- ✅ State file read on startup
- ✅ Personas can be restored (if SSID/password in config)
- ✅ Interface assignments preserved

## 🔌 Phase 6: Multiple Interfaces (Scalability)

### Test 6.1: Multiple Personas Concurrent
```bash
# Start personas on different interfaces
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan1", "ssid": "YourSSID", "password": "YourPassword"}'

curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan2", "ssid": "YourSSID", "password": "YourPassword"}'

curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "bad", "interface": "wlan3", "ssid": "YourSSID", "password": "WrongPassword"}'

# Verify all running
docker ps | grep persona
curl http://localhost:5000/api/personas
```

**Expected Results:**
- ✅ All personas start successfully
- ✅ Each has its own container
- ✅ Each has its own interface
- ✅ All show in dashboard UI
- ✅ No interface conflicts

### Test 6.2: Interface Assignment Validation
```bash
# Try to assign same interface twice
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan1", "ssid": "YourSSID", "password": "YourPassword"}'

# Should fail or show error
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan1", "ssid": "YourSSID", "password": "YourPassword"}'
```

**Expected Results:**
- ✅ Second assignment fails gracefully
- ✅ Error message returned
- ✅ First persona continues running

## 📝 Phase 7: Logging & Monitoring

### Test 7.1: Log Aggregation
```bash
# Start personas
# ... (start 2-3 personas)

# Check aggregated logs via API
curl http://localhost:5000/api/logs/aggregate

# Check logs in dashboard UI (Logs tab)
```

**Expected Results:**
- ✅ Logs from all personas visible
- ✅ Logs include timestamps
- ✅ Logs show persona type and interface
- ✅ Real-time updates (if streaming implemented)

### Test 7.2: Individual Persona Logs
```bash
CONTAINER_ID=$(docker ps | grep persona | awk '{print $1}' | head -1)
curl http://localhost:5000/api/personas/$CONTAINER_ID/logs
```

**Expected Results:**
- ✅ Individual persona logs accessible
- ✅ Logs show connection attempts
- ✅ Traffic generation logs visible
- ✅ MAC rotation logs present

## 🌐 Phase 8: Dashboard UI

### Test 8.1: Status Tab
- [ ] System information displayed
- [ ] Persona count correct
- [ ] Interface count correct
- [ ] Uptime shown
- [ ] Real-time updates working

### Test 8.2: Personas Tab
- [ ] All running personas listed
- [ ] Persona type displayed correctly
- [ ] Interface assignment shown
- [ ] Container status accurate
- [ ] Stop button works
- [ ] Start persona form functional

### Test 8.3: Hardware Tab
- [ ] All interfaces listed
- [ ] Assignment status correct
- [ ] MAC addresses shown
- [ ] Driver information displayed
- [ ] Available interfaces highlighted

### Test 8.4: Logs Tab
- [ ] Logs displayed
- [ ] Filtering works (if implemented)
- [ ] Auto-scroll works
- [ ] Clear logs button works (if implemented)

### Test 8.5: Wi-Fi Config Tab
- [ ] SSID input works
- [ ] Password input works
- [ ] Save button persists config
- [ ] Config loaded on page refresh

## 🛠️ Phase 9: Error Handling

### Test 9.1: Invalid Interface
```bash
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan999", "ssid": "YourSSID", "password": "YourPassword"}'
```

**Expected Results:**
- ✅ Error message returned
- ✅ No container created
- ✅ Dashboard shows error

### Test 9.2: Invalid Credentials
```bash
curl -X POST http://localhost:5000/api/personas \
  -H "Content-Type: application/json" \
  -d '{"persona_type": "good", "interface": "wlan1", "ssid": "NonExistentSSID", "password": "WrongPassword"}'
```

**Expected Results:**
- ✅ Container starts (persona handles connection failure)
- ✅ Logs show connection failures
- ✅ Persona retries connection

### Test 9.3: Container Crash Recovery
```bash
# Start persona
CONTAINER_ID=$(docker ps | grep persona | awk '{print $1}')

# Force kill container
docker kill $CONTAINER_ID

# Check interface returned to host
ip link show wlan1

# Check state updated
curl http://localhost:5000/api/personas
```

**Expected Results:**
- ✅ Interface returned to host
- ✅ State file updated
- ✅ Dashboard reflects stopped persona

## 📈 Phase 10: Performance & Stress Testing

### Test 10.1: Maximum Personas
```bash
# Start personas on all available interfaces
# ... (start personas on wlan0, wlan1, wlan2, wlan3, etc.)

# Monitor system resources
docker stats

# Check dashboard responsiveness
curl http://localhost:5000/api/personas
```

**Expected Results:**
- ✅ All personas start successfully
- ✅ System remains responsive
- ✅ Dashboard loads quickly
- ✅ No memory leaks

### Test 10.2: Rapid Start/Stop
```bash
# Rapidly start and stop personas
for i in {1..10}; do
  curl -X POST http://localhost:5000/api/personas \
    -H "Content-Type: application/json" \
    -d '{"persona_type": "good", "interface": "wlan1", "ssid": "YourSSID", "password": "YourPassword"}'
  sleep 2
  CONTAINER_ID=$(docker ps | grep persona | awk '{print $1}')
  curl -X DELETE http://localhost:5000/api/personas/$CONTAINER_ID
  sleep 2
done
```

**Expected Results:**
- ✅ No interface leaks
- ✅ All containers cleaned up
- ✅ State file remains consistent
- ✅ No orphaned processes

## ✅ Testing Checklist Summary

- [ ] Installation successful
- [ ] Dashboard accessible
- [ ] Interface detection works
- [ ] Interface movement works (single)
- [ ] Interface cleanup works
- [ ] Good client persona works
- [ ] Bad client persona works
- [ ] Wired client persona works
- [ ] MAC rotation works
- [ ] State persistence works
- [ ] Reboot recovery works
- [ ] Multiple personas concurrent
- [ ] Interface assignment validation
- [ ] Log aggregation works
- [ ] Dashboard UI functional
- [ ] Error handling works
- [ ] Container crash recovery
- [ ] Performance acceptable
- [ ] No resource leaks

## 🐛 Common Issues & Solutions

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed troubleshooting steps.

## 📝 Test Results Template

For each test phase, document:
- **Date**: 
- **Tester**: 
- **Hardware**: (Pi model, number of USB adapters)
- **Software**: (OS version, Docker version)
- **Results**: (Pass/Fail with notes)
- **Issues Found**: 
- **Screenshots/Logs**: 

---

**Next Steps After Testing:**
1. Document any bugs found
2. Create GitHub issues for critical bugs
3. Refine based on test feedback
4. Update documentation with findings
5. Prepare for production deployment
