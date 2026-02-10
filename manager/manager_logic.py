"""
Manager Logic: Handles container lifecycle and persona management.
This module orchestrates the creation, management, and cleanup of persona containers.
"""

import docker
import logging
import json
import os
import time
import subprocess
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from .interface_manager import InterfaceManager

logger = logging.getLogger(__name__)


class PersonaManager:
    """Manages persona container lifecycles and interface assignments."""
    
    # Persona type configurations
    PERSONA_CONFIGS = {
        'good': {
            'hostname': 'CNXNMist-WiFiGood',
            'image': 'wifi-dashboard-persona:latest',
            'traffic_intensity': 'medium',
            'roaming_enabled': True,
        },
        'bad': {
            'hostname': 'CNXNMist-WiFiBad',
            'image': 'wifi-dashboard-persona:latest',
            'traffic_intensity': 'light',
            'roaming_enabled': False,
        },
        'wired': {
            'hostname': 'CNXNMist-Wired',
            'image': 'wifi-dashboard-persona:latest',
            'traffic_intensity': 'heavy',
            'roaming_enabled': False,
        }
    }
    
    def __init__(self, state_dir: str = "/app/state"):
        # Lazy initialization - don't connect to Docker until needed
        self.client = None
        self._client_initialized = False
        self.interface_manager = InterfaceManager()  # This no longer connects immediately
        self.state_dir = state_dir
        self.state_file = os.path.join(state_dir, "personas.json")
        os.makedirs(state_dir, exist_ok=True)
        
        # Load persisted state (doesn't require Docker)
        self.state = self._load_state()
        logger.info(f"PersonaManager initialized with state_dir: {state_dir}")
    
    def _ensure_client(self):
        """Lazy initialization of Docker client"""
        if self._client_initialized and self.client is not None:
            return True
        
        try:
            self.client = docker.from_env()
            self.client.ping()
            self._client_initialized = True
            logger.info("Docker client initialized successfully")
            return True
        except docker.errors.DockerException as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            logger.error("Make sure Docker socket is accessible: /var/run/docker.sock")
            self.client = None
            self._client_initialized = False
            return False
        except Exception as e:
            logger.error(f"Unexpected error initializing Docker client: {e}")
            self.client = None
            self._client_initialized = False
            return False
            
            # Load persisted state
            self.state = self._load_state()
            
            logger.info(f"PersonaManager initialized with state_dir: {state_dir}")
            
        except docker.errors.DockerException as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise
        except Exception as e:
            logger.exception(f"Failed to initialize PersonaManager: {e}")
            raise

    def _load_state(self) -> Dict:
        """Load persisted persona state from disk."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load state: {e}")
        return {
            'personas': {},
            'interfaces': {},
            'last_updated': None
        }

    def _save_state(self):
        """Persist persona state to disk."""
        try:
            self.state['last_updated'] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def start_persona(
        self,
        persona_type: str,
        interface: str,
        ssid: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Start a persona container and move the specified interface into it.
        
        Args:
            persona_type: Type of persona ('good', 'bad', 'wired')
            interface: Physical interface name (e.g., 'wlan1')
            ssid: Wi-Fi SSID (optional, uses config if not provided)
            password: Wi-Fi password (optional, uses config if not provided)
            **kwargs: Additional persona-specific parameters
        
        Returns:
            Tuple of (success: bool, message: str, container_id: str or None)
        """
        if persona_type not in self.PERSONA_CONFIGS:
            return False, f"Unknown persona type: {persona_type}", None

        # Clean up stale state first
        self._cleanup_stale_state()
        
        # Check if interface is already assigned
        if interface in self.state.get('interfaces', {}):
            existing = self.state['interfaces'][interface]
            container_id = existing.get('container_id')
            container_name = existing.get('container_name')
            
            # Verify the container actually exists
            container_exists = False
            if self._ensure_client():
                try:
                    if container_id:
                        try:
                            self.client.containers.get(container_id)
                            container_exists = True
                        except docker.errors.NotFound:
                            pass
                    if not container_exists and container_name:
                        try:
                            self.client.containers.get(container_name)
                            container_exists = True
                        except docker.errors.NotFound:
                            pass
                except:
                    pass
            
            if container_exists:
                return False, f"Interface {interface} already assigned to {container_name}", None
            else:
                # Container doesn't exist, clean up stale assignment
                logger.info(f"Removing stale interface assignment for {interface} (container {container_name} doesn't exist)")
                del self.state['interfaces'][interface]
                self._save_state()

        config = self.PERSONA_CONFIGS[persona_type]
        container_name = f"persona-{persona_type}-{interface}-{int(time.time())}"

        try:
            # Create container
            logger.info(f"Creating persona container: {container_name}")
            
            # Build environment variables
            env_vars = {
                'PERSONA_TYPE': persona_type,
                'INTERFACE': 'eth_sim' if persona_type == 'wired' else 'wlan_sim',  # Standardized name inside container
                'HOSTNAME': config['hostname'],
                'TRAFFIC_INTENSITY': config.get('traffic_intensity', 'medium'),
                'ROAMING_ENABLED': str(config.get('roaming_enabled', False)).lower(),
            }
            
            if ssid:
                env_vars['SSID'] = ssid
            if password:
                env_vars['PASSWORD'] = password
            
            # Add any additional kwargs as environment variables
            for key, value in kwargs.items():
                env_vars[key.upper()] = str(value)

            # Ensure Docker client is initialized
            if not self._ensure_client():
                return False, "Docker client not available - check Docker socket permissions", None
            
            # Create container with host network mode for Wi-Fi access
            container = self.client.containers.create(
                image=config['image'],
                name=container_name,
                network_mode='none',  # We'll move the interface manually
                pid_mode='host',  # Need host PID namespace for interface operations
                privileged=True,  # Required for Wi-Fi operations
                environment=env_vars,
                detach=True,
                auto_remove=False,  # We'll handle cleanup
                volumes={
                    '/var/run/docker.sock': {'bind': '/var/run/docker.sock', 'mode': 'ro'},
                }
            )

            # Start container
            container.start()
            logger.info(f"Started container: {container_name} (ID: {container.id})")

            # Wait a moment for container to initialize
            time.sleep(2)

            # Move interface into container
            # For wired personas, use 'eth_sim' as the target name, otherwise 'wlan_sim'
            target_name = 'eth_sim' if persona_type == 'wired' else 'wlan_sim'
            success, msg = self.interface_manager.move_to_container(
                interface=interface,
                container_name=container_name,
                target_name=target_name
            )

            if not success:
                # Cleanup on failure
                try:
                    container.stop(timeout=5)
                    container.remove()
                except:
                    pass
                return False, f"Failed to move interface: {msg}", None

            # Update state
            self.state.setdefault('personas', {})[container.id] = {
                'container_name': container_name,
                'persona_type': persona_type,
                'interface': interface,
                'hostname': config['hostname'],
                'created_at': datetime.now().isoformat(),
                'status': 'running'
            }
            
            self.state.setdefault('interfaces', {})[interface] = {
                'container_id': container.id,
                'container_name': container_name,
                'persona_type': persona_type,
                'assigned_at': datetime.now().isoformat()
            }
            
            self._save_state()

            return True, f"Persona {persona_type} started on {interface}", container.id

        except docker.errors.ImageNotFound:
            return False, f"Persona image not found: {config['image']}. Run 'docker build -f Dockerfile.persona -t wifi-dashboard-persona:latest .'", None
        except docker.errors.APIError as e:
            return False, f"Docker API error: {e}", None
        except Exception as e:
            logger.exception(f"Failed to start persona: {e}")
            return False, f"Unexpected error: {str(e)}", None

    def stop_persona(self, container_id: Optional[str] = None, container_name: Optional[str] = None) -> Tuple[bool, str]:
        """
        Stop a persona container and return its interface to the host.
        
        Args:
            container_id: Docker container ID
            container_name: Docker container name (alternative to ID)
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self._ensure_client():
            return False, "Docker client not available - check Docker socket permissions"
        
        try:
            if container_name:
                container = self.client.containers.get(container_name)
            elif container_id:
                container = self.client.containers.get(container_id)
            else:
                return False, "Must provide either container_id or container_name"

            container_id = container.id
            container_name = container.name

            # Get interface from state
            interface = None
            for iface, info in self.state.get('interfaces', {}).items():
                if info.get('container_id') == container_id:
                    interface = iface
                    break

            if not interface:
                # Try to get from container metadata
                logger.warning(f"Interface not found in state for {container_name}, attempting recovery")
                interface = 'wlan_sim'  # Fallback

            # Get container PID before stopping
            try:
                container.reload()
                pid = container.attrs['State']['Pid']
            except:
                pid = None

            # Stop container
            try:
                container.stop(timeout=10)
                logger.info(f"Stopped container: {container_name}")
            except docker.errors.NotFound:
                logger.warning(f"Container {container_name} not found (may already be stopped)")
            except Exception as e:
                logger.error(f"Error stopping container: {e}")

            # Return interface to host if we have PID
            if pid and pid > 0:
                if interface:
                    self.interface_manager.return_to_host(interface, pid)
                else:
                    # Try to recover any interface from the container
                    logger.warning("Attempting to recover interface from stopped container")
                    # This is a best-effort recovery
                    try:
                        result = subprocess.run(
                            ["nsenter", "-t", str(pid), "-n", "ip", "link", "show"],
                            capture_output=True,
                            timeout=5,
                            text=True
                        )
                        for line in result.stdout.split('\n'):
                            if 'wlan' in line or 'wlp' in line:
                                iface = line.split(':')[1].strip()
                                self.interface_manager.return_to_host(iface, pid)
                                break
                    except:
                        pass

            # Remove container
            try:
                container.remove()
                logger.info(f"Removed container: {container_name}")
            except:
                pass

            # Update state
            if container_id in self.state.get('personas', {}):
                del self.state['personas'][container_id]
            
            if interface and interface in self.state.get('interfaces', {}):
                del self.state['interfaces'][interface]
            
            self._save_state()

            return True, f"Persona stopped and interface returned to host"

        except docker.errors.NotFound:
            return False, f"Container not found"
        except Exception as e:
            logger.exception(f"Failed to stop persona: {e}")
            return False, f"Error: {str(e)}"

    def _cleanup_stale_state(self):
        """Remove state entries for containers that no longer exist."""
        if not self._ensure_client():
            return
        
        try:
            # Get all actual persona containers
            actual_containers = set()
            all_containers = self.client.containers.list(all=True, filters={'name': 'persona-'})
            for container in all_containers:
                actual_containers.add(container.id)
                actual_containers.add(container.name)
            
            # Clean up personas that don't exist
            personas_to_remove = []
            for container_id, persona_info in self.state.get('personas', {}).items():
                if container_id not in actual_containers and persona_info.get('container_name') not in actual_containers:
                    personas_to_remove.append(container_id)
                    logger.info(f"Cleaning up stale persona state: {persona_info.get('container_name')} (container doesn't exist)")
            
            for container_id in personas_to_remove:
                # Remove from personas
                if container_id in self.state.get('personas', {}):
                    persona_info = self.state['personas'][container_id]
                    interface = persona_info.get('interface')
                    
                    # Remove from interfaces
                    if interface and interface in self.state.get('interfaces', {}):
                        if self.state['interfaces'][interface].get('container_id') == container_id:
                            del self.state['interfaces'][interface]
                            logger.info(f"Removed stale interface assignment: {interface}")
                    
                    del self.state['personas'][container_id]
            
            # Clean up interfaces that reference non-existent containers
            interfaces_to_remove = []
            for interface, info in self.state.get('interfaces', {}).items():
                container_id = info.get('container_id')
                container_name = info.get('container_name')
                if container_id and container_id not in actual_containers:
                    if container_name and container_name not in actual_containers:
                        interfaces_to_remove.append(interface)
                        logger.info(f"Cleaning up stale interface assignment: {interface} (container {container_name} doesn't exist)")
            
            for interface in interfaces_to_remove:
                del self.state['interfaces'][interface]
            
            if personas_to_remove or interfaces_to_remove:
                self._save_state()
                logger.info(f"Cleaned up {len(personas_to_remove)} stale persona(s) and {len(interfaces_to_remove)} stale interface assignment(s)")
                
        except Exception as e:
            logger.warning(f"Error cleaning up stale state: {e}")

    def list_personas(self) -> List[Dict]:
        """List all running persona containers."""
        # Clean up stale state first
        self._cleanup_stale_state()
        
        personas = []
        
        if not self._ensure_client():
            return []  # Return empty list if Docker unavailable
        
        try:
            # Get all containers with our naming pattern
            all_containers = self.client.containers.list(all=True, filters={'name': 'persona-'})
            
            for container in all_containers:
                try:
                    container.reload()
                    attrs = container.attrs
                    
                    persona_info = {
                        'id': container.id,
                        'name': container.name,
                        'status': attrs['State']['Status'],
                        'created': attrs['Created'],
                        'image': attrs['Config']['Image'],
                    }
                    
                    # Get interface assignment from state
                    for iface, info in self.state.get('interfaces', {}).items():
                        if info.get('container_id') == container.id:
                            persona_info['interface'] = iface
                            persona_info['persona_type'] = info.get('persona_type', 'unknown')
                            persona_info['hostname'] = self.state.get('personas', {}).get(container.id, {}).get('hostname', 'unknown')
                            break
                    
                    personas.append(persona_info)
                except Exception as e:
                    logger.warning(f"Error getting info for container {container.id}: {e}")
                    
        except Exception as e:
            logger.error(f"Error listing personas: {e}")
        
        return personas

    def get_persona_logs(self, container_id: str, tail: int = 100) -> List[str]:
        """Get logs from a persona container."""
        if not self._ensure_client():
            return []
        
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail, timestamps=True).decode('utf-8')
            return logs.split('\n')
        except docker.errors.NotFound:
            return [f"Container {container_id} not found"]
        except Exception as e:
            logger.error(f"Error getting logs: {e}")
            return [f"Error: {str(e)}"]

    def get_persona_stats(self, container_id: str) -> Dict:
        """Get statistics for a persona container."""
        if not self._ensure_client():
            return {}
        
        try:
            container = self.client.containers.get(container_id)
            stats = container.stats(stream=False)
            
            # Extract useful metrics
            cpu_stats = stats.get('cpu_stats', {})
            mem_stats = stats.get('memory_stats', {})
            
            return {
                'cpu_percent': self._calculate_cpu_percent(cpu_stats),
                'memory_usage': mem_stats.get('usage', 0),
                'memory_limit': mem_stats.get('limit', 0),
                'network': stats.get('networks', {}),
            }
        except docker.errors.NotFound:
            return {'error': 'Container not found'}
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {'error': str(e)}

    def _calculate_cpu_percent(self, cpu_stats: Dict) -> float:
        """Calculate CPU usage percentage from Docker stats."""
        try:
            cpu_delta = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
            system_cpu = cpu_stats.get('system_cpu_usage', 0)
            
            if system_cpu > 0:
                return (cpu_delta / system_cpu) * 100.0
        except:
            pass
        return 0.0

    def cleanup_all(self):
        """Stop and remove all persona containers (graceful shutdown)."""
        personas = self.list_personas()
        results = []
        
        for persona in personas:
            if persona['status'] in ['running', 'restarting']:
                success, msg = self.stop_persona(container_id=persona['id'])
                results.append({
                    'container': persona['name'],
                    'success': success,
                    'message': msg
                })
        
        return results

    def restore_from_state(self):
        """Restore personas from persisted state (for reboot recovery)."""
        logger.info("Attempting to restore personas from state...")
        
        # Note: This is a simplified version - in production you'd want to
        # restore with the same SSID/password from config
        restored = []
        
        for container_id, persona_info in self.state.get('personas', {}).items():
            if persona_info.get('status') == 'running':
                # Check if container still exists
                if not self._ensure_client():
                    logger.warning("Docker unavailable, skipping persona restoration")
                    continue
                
                try:
                    container = self.client.containers.get(container_id)
                    if container.status == 'running':
                        logger.info(f"Persona {persona_info['container_name']} already running")
                        restored.append(persona_info['container_name'])
                        continue
                except docker.errors.NotFound:
                    pass
                
                # Container doesn't exist, would need to recreate
                # For now, just log - full restore would require SSID/password
                logger.warning(f"Persona {persona_info['container_name']} not found, would need SSID/password to restore")
        
        return restored
