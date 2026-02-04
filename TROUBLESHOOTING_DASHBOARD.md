# Dashboard Access Troubleshooting

## Issue: ERR_EMPTY_RESPONSE when accessing dashboard

### Quick Fixes

#### 1. Fix Docker Permissions

The user needs to be in the docker group:

```bash
# Add user to docker group
sudo usermod -aG docker wlanpi

# Apply changes (choose one):
# Option A: Log out and back in
# Option B: Use newgrp
newgrp docker

# Verify
docker ps
```

#### 2. Check Container Status

```bash
# Check if container is running (with sudo if needed)
sudo docker ps | grep wifi-manager

# Check container logs
sudo docker logs wifi-manager

# Check if Flask is listening
sudo docker exec wifi-manager netstat -tlnp | grep 5000
# Or
sudo docker exec wifi-manager ss -tlnp | grep 5000
```

#### 3. Check Network/Firewall

```bash
# Check if port 5000 is listening on host
sudo netstat -tlnp | grep 5000
# Or
sudo ss -tlnp | grep 5000

# Check firewall (if ufw is installed)
sudo ufw status
sudo ufw allow 5000/tcp

# Check iptables
sudo iptables -L -n | grep 5000
```

#### 4. Test from Different Locations

```bash
# Test from localhost (should work)
curl http://localhost:5000

# Test from host IP
curl http://172.16.50.223:5000

# Test from another machine on the network
# (if possible)
```

#### 5. Restart Container

```bash
cd ~/wifi_dashboard_v2
sudo docker compose restart manager
# Or
sudo docker restart wifi-manager

# Wait a few seconds, then check logs
sudo docker logs wifi-manager -f
```

#### 6. Check Container Network Mode

The container uses `network_mode: host`, so it should be accessible directly:

```bash
# Verify network mode
sudo docker inspect wifi-manager | grep -i networkmode

# Should show: "NetworkMode": "host"
```

### Common Causes

1. **Firewall blocking port 5000** - Most common issue
2. **Container not fully started** - Check logs for errors
3. **Docker permissions** - User not in docker group
4. **Network interface binding** - Flask should bind to 0.0.0.0 (already configured)

### Verification Steps

1. ✅ Container is running: `sudo docker ps | grep wifi-manager`
2. ✅ Flask is listening: `sudo docker exec wifi-manager ss -tlnp | grep 5000`
3. ✅ Port is open on host: `sudo ss -tlnp | grep 5000`
4. ✅ Firewall allows port: `sudo ufw status` (if ufw is used)
5. ✅ Can access from localhost: `curl http://localhost:5000`
6. ✅ Can access from IP: `curl http://172.16.50.223:5000`

### If Still Not Working

Check the manager logs for errors:

```bash
sudo docker logs wifi-manager
```

Look for:
- Python errors
- Import errors
- Port binding errors
- Permission errors
