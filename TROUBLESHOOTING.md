# Troubleshooting Guide

## Docker Socket Permission Issues

If you see "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock":

### Quick Fix

```bash
# Check current socket permissions
ls -la /var/run/docker.sock

# Temporarily fix (until Docker restart)
sudo chmod 666 /var/run/docker.sock

# Or add docker group (if container runs as non-root)
sudo chown root:docker /var/run/docker.sock
```

### Permanent Fix

The container should run as root (`user: "0:0"` in docker-compose.yml). If it still can't access:

1. **Check container user:**
   ```bash
   docker exec wifi-manager id
   # Should show: uid=0(root) gid=0(root)
   ```

2. **Check socket in container:**
   ```bash
   docker exec wifi-manager ls -la /var/run/docker.sock
   ```

3. **Check AppArmor (if enabled):**
   ```bash
   sudo aa-status | grep docker
   ```

4. **Restart container with explicit root:**
   ```bash
   cd /home/pi/wifi_dashboard_v2
   docker-compose down
   docker-compose up -d manager
   ```

## Internal Server Error

If you see "Internal Server Error" in the browser:

1. **Check container logs:**
   ```bash
   docker logs wifi-manager
   ```

2. **Check debug endpoint:**
   ```bash
   curl http://localhost:5000/debug
   ```

3. **Common causes:**
   - Docker socket not accessible (see above)
   - Template files missing
   - Python import errors
   - Manager initialization failures

## Flask App Not Starting

If the container starts but the web interface doesn't work:

1. **Check if Flask is running:**
   ```bash
   docker exec wifi-manager ps aux | grep python
   ```

2. **Check for Python errors:**
   ```bash
   docker logs wifi-manager 2>&1 | grep -i error
   ```

3. **Test Flask directly:**
   ```bash
   docker exec wifi-manager python -c "from manager import app; print('OK')"
   ```

## Interface Movement Issues

If personas can't get interfaces:

1. **Check container privileges:**
   ```bash
   docker inspect wifi-manager | grep -i privileged
   # Should show: "Privileged": true
   ```

2. **Check PID namespace:**
   ```bash
   docker inspect wifi-manager | grep -i pid
   # Should show: "PidMode": "host"
   ```

3. **Test interface movement manually:**
   ```bash
   docker exec wifi-manager iw dev
   ```

## Rebuilding After Fixes

After code updates:

```bash
cd /home/pi/wifi_dashboard_v2
docker-compose down
docker-compose build manager
docker-compose up -d manager
docker logs wifi-manager -f
```
