# Installation Troubleshooting Guide

## Repository Errors on Debian Bullseye

If you see errors like:
```
E: The repository 'http://deb.debian.org/debian bullseye-backports Release' no longer has a Release file.
W: GPG error: ... NO_PUBKEY ...
```

### Quick Fix (Before Re-running Installer)

Run these commands to fix repository issues:

```bash
# 1. Disable problematic backports repository
sudo sed -i 's/^deb/#deb/' /etc/apt/sources.list.d/debian-backports.list 2>/dev/null || true

# 2. Update apt (ignoring key errors)
sudo apt-get update 2>&1 | grep -v "NO_PUBKEY\|EXPKEYSIG" || true

# 3. Install Docker manually
sudo apt-get install -y ca-certificates curl gnupg lsb-release
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 4. Add user to docker group
sudo usermod -aG docker $USER

# 5. Start Docker
sudo systemctl enable docker
sudo systemctl start docker

# 6. Verify Docker works
sudo docker ps
```

### Then Re-run the Installer

After fixing Docker, you can re-run the installer:

```bash
curl -sSL https://raw.githubusercontent.com/danryan06/wifi-dashboard-v2/main/setup.sh | sudo bash
```

The installer will detect Docker is already installed and skip that step.

## Alternative: Manual Installation

If the automated installer continues to fail, you can install manually:

1. **Fix repositories** (see above)
2. **Install Docker** (see above)
3. **Clone and setup manually**:

```bash
cd ~
git clone https://github.com/danryan06/wifi-dashboard-v2.git
cd wifi-dashboard-v2
sudo ./setup.sh
```

## Common Issues

### Docker Socket Permission Errors

```bash
sudo chmod 666 /var/run/docker.sock
# Or add user to docker group (requires logout/login)
sudo usermod -aG docker $USER
newgrp docker
```

### GPG Key Errors

For InfluxData:
```bash
curl -fsSL https://repos.influxdata.com/influxdb.key | sudo apt-key add -
```

For Grafana:
```bash
curl -fsSL https://apt.grafana.com/gpg.key | sudo apt-key add -
```

### Old Repository URLs

If repositories are pointing to old URLs, update them:
```bash
sudo sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list
sudo sed -i 's|http://security.debian.org|https://security.debian.org|g' /etc/apt/sources.list
```
