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

    def list_available_interfaces(self) -> Dict[str, Dict]:
        """
        List all available Wi-Fi interfaces on the host.
        Returns dict mapping interface name to metadata.
        """
        interfaces = {}
        
        try:
            # Get all network interfaces
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True,
                timeout=5,
                text=True
            )
            
            current_iface = None
            for line in result.stdout.split('\n'):
                # Interface line: "2: wlan1: <BROADCAST,MULTICAST,UP,LOWER_UP>"
                if ':' in line and ('wlan' in line or 'wlp' in line):
                    parts = line.split(':')
                    if len(parts) >= 2:
                        current_iface = parts[1].strip()
                        
                        # Get more info about this interface
                        try:
                            phy_name = self.get_phy_name(current_iface)
                            # Get interface state
                            state_result = subprocess.run(
                                ["ip", "link", "show", current_iface],
                                capture_output=True,
                                timeout=5,
                                text=True
                            )
                            state = 'DOWN'
                            if 'state UP' in state_result.stdout or 'UP' in state_result.stdout:
                                state = 'UP'
                            
                            interfaces[current_iface] = {
                                'name': current_iface,
                                'phy': phy_name,
                                'type': 'wifi',
                                'state': state,
                                'available': True
                            }
                        except Exception as e:
                            logger.debug(f"Could not get full info for {current_iface}: {e}")
                            # Still add it with basic info
                            interfaces[current_iface] = {
                                'name': current_iface,
                                'type': 'wifi',
                                'state': 'unknown',
                                'available': True
                            }
                            
        except Exception as e:
            logger.error(f"Error listing interfaces: {e}")
        
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
