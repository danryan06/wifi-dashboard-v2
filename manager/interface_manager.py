"""
InterfaceManager: Handles moving physical Wi-Fi interfaces into Docker container namespaces.
This is the core "lift & shift" mechanism for the containerized persona model.
"""

import docker
import subprocess
import time
import logging
import os
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)


class InterfaceManager:
    """Handles moving physical Wi-Fi interfaces into Docker container namespaces."""
    
    def __init__(self):
        # Lazy initialization - don't connect until actually needed
        self.client = None
        self._initialized = False
    
    def _ensure_client(self):
        """Lazy initialization of Docker client"""
        if self._initialized and self.client is not None:
            return True
        
        try:
            # Try to connect to Docker socket
            self.client = docker.from_env()
            # Test the connection
            self.client.ping()
            self._initialized = True
            logger.info("Docker client initialized successfully")
            return True
        except docker.errors.DockerException as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            logger.error("Make sure Docker socket is accessible: /var/run/docker.sock")
            self.client = None
            self._initialized = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error initializing Docker client: {e}")
            self.client = None
            self._initialized = False
            return False

    def get_phy_name(self, interface: str) -> Optional[str]:
        """Finds the 'phyX' name for a given 'wlanX' interface."""
        try:
            result = subprocess.check_output(
                ["iw", "dev", interface, "info"],
                stderr=subprocess.DEVNULL,
                timeout=5
            ).decode()
            
            for line in result.split('\n'):
                if "wiphy" in line:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        return f"phy{parts[1]}"
            
            logger.warning(f"Could not find phy name for {interface}, using phy0 as fallback")
            return "phy0"
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout getting phy name for {interface}")
            return None
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get phy name for {interface}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting phy name: {e}")
            return None

    def move_to_container(
        self, 
        interface: str, 
        container_name: str,
        target_name: str = "wlan_sim"
    ) -> Tuple[bool, str]:
        """
        Moves a physical interface (wlanX) into a container's network namespace.
        
        Args:
            interface: Physical interface name (e.g., "wlan1")
            container_name: Docker container name
            target_name: Name to use inside container (default: "wlan_sim")
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self._ensure_client():
            return False, "Docker client not available - check Docker socket permissions"
        
        try:
            container = self.client.containers.get(container_name)
            pid = container.attrs['State']['Pid']
            
            if pid == 0:
                return False, f"Container {container_name} is not running (PID=0)"

            logger.info(f"Moving {interface} to container {container_name} (PID: {pid})")

            # Get phy name for wireless interfaces
            phy_name = self.get_phy_name(interface)
            if not phy_name:
                return False, f"Could not determine phy name for {interface}"

            # 1. Bring the interface down on the host
            try:
                subprocess.run(
                    ["ip", "link", "set", interface, "down"],
                    check=True,
                    timeout=5,
                    capture_output=True
                )
            except subprocess.CalledProcessError as e:
                logger.warning(f"Interface {interface} may already be down: {e}")

            # 2. Move the interface to the container's PID namespace using iw
            # This is the critical step - moving the wireless PHY into the container
            try:
                subprocess.run(
                    ["iw", "phy", phy_name, "set", "netns", str(pid)],
                    check=True,
                    timeout=10,
                    capture_output=True
                )
                logger.info(f"Successfully moved {interface} (phy: {phy_name}) to container namespace")
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode() if e.stderr else str(e)
                return False, f"Failed to move interface to container namespace: {error_msg}"

            # 3. Wait a moment for the interface to appear in the container
            time.sleep(0.5)

            # 4. Rename and bring up inside the container via nsenter
            # Renaming to 'wlan_sim' means traffic scripts are always the same
            try:
                # First, find what the interface is called in the container
                result = subprocess.run(
                    ["nsenter", "-t", str(pid), "-n", "ip", "link", "show"],
                    capture_output=True,
                    timeout=5,
                    text=True
                )
                
                # Find the interface (it might still be wlanX or already renamed)
                actual_name = interface
                for line in result.stdout.split('\n'):
                    if f": {interface}:" in line or f": {interface}@" in line:
                        actual_name = interface
                        break
                
                # Rename to standardized name
                subprocess.run(
                    ["nsenter", "-t", str(pid), "-n", 
                     "ip", "link", "set", actual_name, "name", target_name],
                    check=True,
                    timeout=5,
                    capture_output=True
                )
                
                # Bring it up
                subprocess.run(
                    ["nsenter", "-t", str(pid), "-n", 
                     "ip", "link", "set", target_name, "up"],
                    check=True,
                    timeout=5,
                    capture_output=True
                )
                
                logger.info(f"Successfully renamed {interface} to {target_name} in container")
                return True, f"Interface {interface} moved to container as {target_name}"
                
            except subprocess.CalledProcessError as e:
                error_msg = e.stderr.decode() if e.stderr else str(e)
                logger.error(f"Failed to configure interface in container: {error_msg}")
                # Try to return interface to host as cleanup
                self.return_to_host(interface, pid)
                return False, f"Failed to configure interface in container: {error_msg}"

        except docker.errors.NotFound:
            return False, f"Container {container_name} not found"
        except docker.errors.APIError as e:
            return False, f"Docker API error: {e}"
        except Exception as e:
            logger.exception(f"Unexpected error moving interface: {e}")
            return False, f"Unexpected error: {str(e)}"

    def return_to_host(self, interface: str, container_pid: int) -> bool:
        """
        Manual recovery of an interface if a container crashes.
        Moves interface back to host namespace (PID 1).
        """
        try:
            logger.info(f"Returning {interface} to host namespace from PID {container_pid}")
            
            # Move interface back to host namespace (PID 1)
            subprocess.run(
                ["nsenter", "-t", str(container_pid), "-n", 
                 "ip", "link", "set", interface, "netns", "1"],
                check=True,
                timeout=10,
                capture_output=True
            )
            
            # Bring it up on host
            time.sleep(0.5)
            subprocess.run(
                ["ip", "link", "set", interface, "up"],
                check=False,  # Don't fail if already up
                timeout=5,
                capture_output=True
            )
            
            logger.info(f"Successfully returned {interface} to host")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to return interface to host: {e}")
            # Try alternative method using iw
            try:
                phy_name = self.get_phy_name(interface)
                if phy_name:
                    subprocess.run(
                        ["nsenter", "-t", str(container_pid), "-n",
                         "iw", "phy", phy_name, "set", "netns", "1"],
                        check=True,
                        timeout=10,
                        capture_output=True
                    )
                    return True
            except Exception as e2:
                logger.error(f"Alternative recovery method also failed: {e2}")
            
            return False
        except Exception as e:
            logger.exception(f"Unexpected error returning interface to host: {e}")
            return False

    def list_available_interfaces(self, include_ethernet: bool = True) -> Dict[str, Dict]:
        """
        List all available network interfaces on the host.
        Uses multiple methods to ensure we catch all interfaces.
        
        Args:
            include_ethernet: If True, also include ethernet interfaces (for wired personas)
        
        Returns:
            dict mapping interface name to metadata.
        """
        interfaces = {}
        
        try:
            # Method 1: Use 'iw dev' to find all wireless interfaces (most reliable)
            try:
                iw_result = subprocess.run(
                    ["iw", "dev"],
                    capture_output=True,
                    timeout=5,
                    text=True
                )
                if iw_result.returncode == 0:
                    current_iface = None
                    for line in iw_result.stdout.split('\n'):
                        # Look for "Interface wlanX" lines
                        if 'Interface' in line:
                            parts = line.split()
                            if len(parts) >= 2:
                                current_iface = parts[1].strip()
                                # Initialize interface entry
                                if current_iface not in interfaces:
                                    interfaces[current_iface] = {
                                        'name': current_iface,
                                        'type': 'wifi',
                                        'state': 'unknown',
                                        'available': True
                                    }
            except Exception as e:
                logger.debug(f"iw dev failed: {e}")
            
            # Method 2: Use 'ip link show' to find all network interfaces
            try:
                ip_result = subprocess.run(
                    ["ip", "link", "show"],
                    capture_output=True,
                    timeout=5,
                    text=True
                )
                
                current_iface = None
                for line in ip_result.stdout.split('\n'):
                    # Interface line: "2: wlan1: <BROADCAST,MULTICAST,UP,LOWER_UP>"
                    if ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 2:
                            potential_iface = parts[1].strip().split('@')[0]  # Remove @link suffix
                            
                            # Check if it's a wireless interface (wlan, wlp, or check via iw)
                            is_wifi = False
                            if 'wlan' in potential_iface or 'wlp' in potential_iface:
                                is_wifi = True
                            else:
                                # Check if it's a wireless interface using iw
                                try:
                                    check_result = subprocess.run(
                                        ["iw", "dev", potential_iface, "info"],
                                        capture_output=True,
                                        timeout=2,
                                        text=True
                                    )
                                    if check_result.returncode == 0:
                                        is_wifi = True
                                except:
                                    pass  # Not a wireless interface
                            
                            if is_wifi:
                                current_iface = potential_iface
                                if current_iface not in interfaces:
                                    interfaces[current_iface] = {
                                        'name': current_iface,
                                        'type': 'wifi',
                                        'state': 'unknown',
                                        'available': True
                                    }
            except Exception as e:
                logger.debug(f"ip link show failed: {e}")
            
            # Method 3: Check /sys/class/net/ for any interfaces we might have missed
            try:
                if os.path.exists('/sys/class/net'):
                    for iface_name in os.listdir('/sys/class/net'):
                        # Skip loopback and virtual interfaces
                        if iface_name.startswith('lo') or iface_name.startswith('docker') or iface_name.startswith('br-'):
                            continue
                        
                        # Check if it's a wireless interface
                        is_wifi = False
                        if 'wlan' in iface_name or 'wlp' in iface_name:
                            is_wifi = True
                        else:
                            # Check using iw
                            try:
                                check_result = subprocess.run(
                                    ["iw", "dev", iface_name, "info"],
                                    capture_output=True,
                                    timeout=2,
                                    text=True
                                )
                                if check_result.returncode == 0:
                                    is_wifi = True
                            except:
                                pass
                        
                        if is_wifi and iface_name not in interfaces:
                            interfaces[iface_name] = {
                                'name': iface_name,
                                'type': 'wifi',
                                'state': 'unknown',
                                'available': True
                            }
            except Exception as e:
                logger.debug(f"sys/class/net check failed: {e}")
            
            # Method 4: Add ethernet interfaces if requested (for wired personas)
            if include_ethernet:
                try:
                    ip_result = subprocess.run(
                        ["ip", "link", "show"],
                        capture_output=True,
                        timeout=5,
                        text=True
                    )
                    
                    for line in ip_result.stdout.split('\n'):
                        if ':' in line:
                            parts = line.split(':')
                            if len(parts) >= 2:
                                potential_iface = parts[1].strip().split('@')[0]
                                
                                # Check if it's an ethernet interface (eth, enp, eno, etc.)
                                is_ethernet = False
                                if potential_iface.startswith('eth') or \
                                   potential_iface.startswith('enp') or \
                                   potential_iface.startswith('eno') or \
                                   potential_iface.startswith('ens'):
                                    is_ethernet = True
                                
                                # Skip if already added or if it's a virtual interface
                                if is_ethernet and potential_iface not in interfaces:
                                    # Skip loopback, docker, bridge interfaces
                                    if not potential_iface.startswith('lo') and \
                                       not potential_iface.startswith('docker') and \
                                       not potential_iface.startswith('br-') and \
                                       not potential_iface.startswith('pan'):
                                        interfaces[potential_iface] = {
                                            'name': potential_iface,
                                            'type': 'ethernet',
                                            'state': 'unknown',
                                            'available': True
                                        }
                except Exception as e:
                    logger.debug(f"Failed to add ethernet interfaces: {e}")
            
            # Filter out interfaces we don't want to show
            interfaces_to_remove = []
            for iface_name in list(interfaces.keys()):
                # Skip monitor interfaces (mon0, mon1, etc.)
                if iface_name.startswith('mon'):
                    interfaces_to_remove.append(iface_name)
                    continue
                
                # Skip container interface names (wlan_sim is the standard name inside containers)
                if iface_name == 'wlan_sim':
                    interfaces_to_remove.append(iface_name)
                    continue
                
                # Check if interface is in a container namespace (not on host)
                # If we can't get info about it from the host, it's probably in a container
                try:
                    result = subprocess.run(
                        ["iw", "dev", iface_name, "info"],
                        capture_output=True,
                        timeout=2,
                        text=True
                    )
                    # If iw fails, it might be in a container - but don't remove yet,
                    # let's check with ip link instead
                    if result.returncode != 0:
                        ip_result = subprocess.run(
                            ["ip", "link", "show", iface_name],
                            capture_output=True,
                            timeout=2,
                            text=True
                        )
                        # If both fail, interface doesn't exist on host (might be in container)
                        if ip_result.returncode != 0:
                            # Don't remove - might just be down, let it through
                            pass
                except:
                    pass  # Keep the interface if we can't check
            
            # Remove filtered interfaces
            for iface_name in interfaces_to_remove:
                interfaces.pop(iface_name, None)
                logger.debug(f"Filtered out interface: {iface_name}")
            
            # Now enrich all interfaces with detailed info
            for iface_name in list(interfaces.keys()):
                try:
                    # Get PHY name for wireless interfaces only
                    if interfaces[iface_name].get('type') == 'wifi':
                        phy_name = self.get_phy_name(iface_name)
                        if phy_name:
                            interfaces[iface_name]['phy'] = phy_name
                    
                    # Get interface state
                    state_result = subprocess.run(
                        ["ip", "link", "show", iface_name],
                        capture_output=True,
                        timeout=5,
                        text=True
                    )
                    if state_result.returncode == 0:
                        state = 'DOWN'
                        if 'state UP' in state_result.stdout or 'UP' in state_result.stdout:
                            state = 'UP'
                        interfaces[iface_name]['state'] = state
                    else:
                        interfaces[iface_name]['state'] = 'DOWN'
                        
                except Exception as e:
                    logger.debug(f"Could not get full info for {iface_name}: {e}")
                    # Keep basic info we have
                    if 'state' not in interfaces[iface_name]:
                        interfaces[iface_name]['state'] = 'unknown'
                            
        except Exception as e:
            logger.error(f"Error listing interfaces: {e}")
        
        interface_types = {}
        for iface, info in interfaces.items():
            iface_type = info.get('type', 'unknown')
            interface_types[iface_type] = interface_types.get(iface_type, 0) + 1
        
        logger.info(f"Found {len(interfaces)} interfaces: {interface_types}")
        return interfaces

    def get_interface_status(self, interface: str) -> Dict:
        """Get current status of an interface."""
        try:
            result = subprocess.run(
                ["ip", "link", "show", interface],
                capture_output=True,
                timeout=5,
                text=True
            )
            
            if result.returncode != 0:
                return {'exists': False}
            
            # Parse interface state
            state = 'DOWN'
            if 'state UP' in result.stdout:
                state = 'UP'
            
            phy_name = self.get_phy_name(interface)
            
            return {
                'exists': True,
                'state': state,
                'phy': phy_name,
                'name': interface
            }
        except Exception as e:
            logger.error(f"Error getting interface status: {e}")
            return {'exists': False, 'error': str(e)}
