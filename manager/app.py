"""
Flask Application for Wi-Fi Dashboard Manager
Updated to use Docker SDK instead of systemd/subprocess
"""

from flask import Flask, render_template, request, redirect, jsonify, flash, send_from_directory
import os
import logging
import time
import json
import traceback
from datetime import datetime
import threading
import psutil
from .manager_logic import PersonaManager
from .interface_manager import InterfaceManager

# Diagnostics module is optional at runtime: if missing, the manager should still boot.
_diagnostics_import_error = None
try:
    from .driver_diagnostics import run_diagnostics
except Exception as e:
    _diagnostics_import_error = str(e)

    def run_diagnostics():
        return {
            "summary": {
                "issues_found": 1,
                "recommendations_count": 1,
            },
            "issues": [{
                "type": "diagnostics_module_missing",
                "severity": "high",
                "message": f"Diagnostics module unavailable: {_diagnostics_import_error}",
            }],
            "recommendations": [{
                "type": "reinstall_manager",
                "message": "Rebuild manager image or reinstall to restore diagnostics module.",
            }],
        }

# Determine base directory - handle both development and container environments
if os.path.exists("/app"):
    # Running in container
    BASE_DIR = "/app"
else:
    # Running locally
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load version
VERSION_FILE = os.path.join(BASE_DIR, "VERSION")
VERSION = "2.0.0"  # Default fallback
if os.path.exists(VERSION_FILE):
    try:
        with open(VERSION_FILE, 'r') as f:
            VERSION = f.read().strip()
    except:
        pass

# Configure Flask with explicit template and static folders
template_dir = os.path.join(BASE_DIR, "templates")
static_dir = os.path.join(BASE_DIR, "manager", "static")

app = Flask(__name__, 
            template_folder=template_dir,
            static_folder=static_dir,
            static_url_path='/static')
app.secret_key = 'wifi-test-dashboard-secret-key'

# Configuration paths
CONFIG_FILE = os.path.join(BASE_DIR, "configs", "ssid.conf")
SETTINGS_FILE = os.path.join(BASE_DIR, "configs", "settings.conf")
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATS_DIR = os.path.join(BASE_DIR, "stats")
STATE_DIR = os.path.join(BASE_DIR, "state")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(STATS_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)

# Setup logging FIRST (before manager initialization)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "manager.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
if _diagnostics_import_error:
    logger.warning(f"Diagnostics module unavailable at startup: {_diagnostics_import_error}")

# Initialize managers with error handling (lazy initialization)
persona_manager = None
interface_manager = None

def initialize_managers():
    """Lazy initialization of managers - called on first use"""
    global persona_manager, interface_manager
    
    if persona_manager is not None and interface_manager is not None:
        return True  # Already initialized
    
    try:
        logger.info("Initializing PersonaManager and InterfaceManager...")
        persona_manager = PersonaManager(state_dir=STATE_DIR)
        interface_manager = InterfaceManager()
        logger.info("✅ Managers initialized successfully")
        return True
    except Exception as e:
        logger.exception(f"Failed to initialize managers: {e}")
        logger.error("Application will run in limited mode - Docker features unavailable")
        return False

# Try to initialize, but don't fail if Docker isn't available
try:
    initialize_managers()
except Exception as e:
    logger.error(f"Manager initialization failed: {e}")

# State tracking for throughput
_state_lock = threading.Lock()
_state = {
    "prev": {},
    "totals": {},
    "last_ts": None,
}
_MB = 1024 * 1024


def read_config():
    """Read SSID configuration"""
    ssid, password = "", ""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                lines = [line.strip() for line in f.readlines()]
                if len(lines) >= 2:
                    ssid, password = lines[0], lines[1]
        return ssid, password
    except Exception as e:
        logger.error(f"Error reading config: {e}")
        return "", ""


def write_config(ssid, password):
    """Write SSID configuration"""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            f.write(f"{ssid}\n{password}\n")
        os.chmod(CONFIG_FILE, 0o600)
        return True
    except Exception as e:
        logger.error(f"Error writing config: {e}")
        return False


@app.route("/")
def index():
    """Main dashboard page"""
    try:
        ssid, _ = read_config()
        template_path = os.path.join(app.template_folder, "dashboard.html")
        if not os.path.exists(template_path):
            logger.error(f"Template not found at: {template_path}")
            return f"<h1>Error</h1><p>Template not found at: {template_path}</p><p>Template folder: {app.template_folder}</p>", 500
        return render_template("dashboard.html", ssid=ssid, version=VERSION)
    except Exception as e:
        logger.exception(f"Error in index route: {e}")
        return f"<h1>Error</h1><p>Failed to load dashboard: {str(e)}</p><pre>{traceback.format_exc()}</pre>", 500


@app.route("/static/<path:filename>")
def static_files(filename):
    """Serve static files"""
    try:
        static_dir = os.path.join(BASE_DIR, "manager", "static")
        if not os.path.exists(static_dir):
            logger.warning(f"Static directory not found: {static_dir}")
            return "Static files not found", 404
        response = send_from_directory(static_dir, filename)
        # Add cache-busting headers for JS/CSS files
        if filename.endswith(('.js', '.css')):
            response.cache_control.no_cache = True
            response.cache_control.must_revalidate = True
        return response
    except Exception as e:
        logger.exception(f"Error serving static file {filename}: {e}")
        return f"Error: {str(e)}", 500


@app.route("/api/version")
def api_version():
    """Get current version"""
    return jsonify({"version": VERSION})

@app.route("/status")
def status():
    """API endpoint for status information"""
    try:
        # Try to initialize managers if not already done
        initialize_managers()
        
        ssid, password = read_config()
        
        # Get persona status
        personas = []
        if persona_manager:
            try:
                personas = persona_manager.list_personas()
            except Exception as e:
                logger.error(f"Error listing personas: {e}")
        
        # Get available interfaces
        interfaces = {}
        if interface_manager:
            try:
                interfaces = interface_manager.list_available_interfaces()
            except Exception as e:
                logger.error(f"Error listing interfaces: {e}")
        
        # Get system info
        try:
            import subprocess
            ip_result = subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=5)
            ip_address = ip_result.stdout.strip().split()[0] if ip_result.stdout.strip() else "Unknown"
        except:
            ip_address = "Unknown"
        
        return jsonify({
            "ssid": ssid,
            "password_masked": "*" * len(password) if password else "",
            "personas": personas,
            "interfaces": interfaces,
            "system_info": {
                "ip_address": ip_address,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            },
            "version": VERSION,
            "success": True
        })
    except Exception as e:
        logger.error(f"Error in status endpoint: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas", methods=["GET"])
def api_list_personas():
    """List all persona containers"""
    try:
        if not initialize_managers():
            return jsonify({
                "success": False, 
                "error": "Docker not available. Check container logs: docker logs wifi-manager"
            }), 500
        personas = persona_manager.list_personas()
        return jsonify({"success": True, "personas": personas})
    except Exception as e:
        logger.exception(f"Error listing personas: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas", methods=["POST"])
def api_start_persona():
    """Start a new persona container"""
    try:
        if not persona_manager:
            return jsonify({"success": False, "error": "PersonaManager not initialized"}), 500
            
        data = request.get_json()
        persona_type = data.get("persona_type")
        interface = data.get("interface")
        ssid = data.get("ssid")
        password = data.get("password")
        
        if not persona_type or not interface:
            return jsonify({"success": False, "error": "persona_type and interface required"}), 400
        
        # Use config SSID/password if not provided
        if not ssid or not password:
            ssid, password = read_config()
        
        # For wired personas, no Wi-Fi config needed
        if persona_type == 'wired':
            ssid = None
            password = None
        # For bad personas, only SSID is needed (they use wrong password)
        elif persona_type == 'bad':
            if not ssid:
                return jsonify({"success": False, "error": "SSID required for bad persona"}), 400
            password = None  # Bad personas don't use the correct password
        # For good personas, both are required
        elif persona_type == 'good':
            if not ssid or not password:
                return jsonify({"success": False, "error": "SSID and password required for good persona"}), 400
        
        success, message, container_id = persona_manager.start_persona(
            persona_type=persona_type,
            interface=interface,
            ssid=ssid,
            password=password
        )
        
        if success:
            return jsonify({
                "success": True,
                "message": message,
                "container_id": container_id
            })
        else:
            return jsonify({"success": False, "error": message}), 500
            
    except Exception as e:
        logger.error(f"Error starting persona: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas/<container_id>", methods=["DELETE"])
def api_stop_persona(container_id):
    """Stop a persona container"""
    try:
        if not persona_manager:
            return jsonify({"success": False, "error": "PersonaManager not initialized"}), 500
        success, message = persona_manager.stop_persona(container_id=container_id)
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "error": message}), 500
            
    except Exception as e:
        logger.error(f"Error stopping persona: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas/<container_id>/logs")
def api_persona_logs(container_id):
    """Get logs from a persona container"""
    try:
        if not persona_manager:
            return jsonify({"success": False, "error": "PersonaManager not initialized"}), 500
        tail = int(request.args.get("tail", 100))
        logs = persona_manager.get_persona_logs(container_id, tail=tail)
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        logger.exception(f"Error getting logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs/manager")
def api_manager_logs():
    """Get logs from the manager container"""
    try:
        tail = int(request.args.get("tail", 500))
        log_file = os.path.join(LOG_DIR, "manager.log")
        
        if not os.path.exists(log_file):
            return jsonify({"success": True, "logs": ["Log file not found"]})
        
        # Read last N lines from log file
        with open(log_file, 'r') as f:
            lines = f.readlines()
            logs = [line.rstrip() for line in lines[-tail:]]
        
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        logger.exception(f"Error getting manager logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs/aggregate")
def api_aggregate_logs():
    """Get aggregated logs from all persona containers"""
    try:
        if not persona_manager:
            return jsonify({"success": False, "error": "PersonaManager not initialized"}), 500
        personas = persona_manager.list_personas()
        aggregated = {}
        
        for persona in personas:
            if persona.get('status') == 'running':
                try:
                    logs = persona_manager.get_persona_logs(persona['id'], tail=50)
                    aggregated[persona['id']] = {
                        'name': persona['name'],
                        'type': persona.get('persona_type', 'unknown'),
                        'interface': persona.get('interface', 'unknown'),
                        'logs': logs
                    }
                except Exception as e:
                    logger.warning(f"Failed to get logs for {persona['id']}: {e}")
        
        return jsonify({"success": True, "aggregated": aggregated})
    except Exception as e:
        logger.exception(f"Error aggregating logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/interfaces")
def api_interfaces():
    """Get available network interfaces"""
    try:
        # Determine host management interface (default route) to protect it from assignment.
        protected_iface = None
        try:
            import subprocess
            route_result = subprocess.run(
                ['ip', 'route', 'show', 'default'],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in route_result.stdout.split('\n'):
                parts = line.split()
                if 'dev' in parts:
                    idx = parts.index('dev')
                    if idx + 1 < len(parts):
                        protected_iface = parts[idx + 1].strip()
                        break
        except Exception as e:
            logger.debug(f"Could not determine protected interface: {e}")

        # Try to initialize, but interfaces can work without Docker
        if interface_manager is None:
            initialize_managers()
        
        if not interface_manager:
            # Fallback: use basic system commands
            import subprocess
            result = subprocess.run(['ip', 'link', 'show'], capture_output=True, text=True, timeout=5)
            interfaces = {}
            for line in result.stdout.split('\n'):
                if ':' in line and ('wlan' in line or 'eth' in line):
                    parts = line.split(':')
                    if len(parts) >= 2:
                        iface = parts[1].strip()
                        # Get interface state
                        state = 'DOWN'
                        if 'state UP' in line or 'UP' in line:
                            state = 'UP'
                        interfaces[iface] = {
                            'name': iface, 
                            'type': 'wifi' if 'wlan' in iface else 'ethernet',
                            'state': state,
                            'available': True,
                            'assignable': True
                        }
                        if protected_iface and iface == protected_iface:
                            interfaces[iface]['available'] = False
                            interfaces[iface]['assignable'] = False
                            interfaces[iface]['protected'] = True
                            interfaces[iface]['reason'] = 'Management/default-route interface'
            return jsonify({"success": True, "interfaces": interfaces, "note": "Basic mode - Docker unavailable"})
        
        interfaces = interface_manager.list_available_interfaces(include_ethernet=True)
        # Ensure all interfaces have required fields for display
        for iface_name, iface_info in interfaces.items():
            if 'state' not in iface_info:
                iface_info['state'] = 'unknown'
            if 'type' not in iface_info:
                iface_info['type'] = 'wifi' if 'wlan' in iface_name else 'ethernet'
            if 'assignable' not in iface_info:
                iface_info['assignable'] = True
            # Mark management/default-route interface as protected.
            if protected_iface and iface_name == protected_iface:
                iface_info['available'] = False
                iface_info['assignable'] = False
                iface_info['protected'] = True
                iface_info['reason'] = 'Management/default-route interface'
        
        return jsonify({"success": True, "interfaces": interfaces})
    except Exception as e:
        logger.exception(f"Error getting interfaces: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/diagnostics")
def api_diagnostics():
    """Get driver and interface diagnostics"""
    try:
        diagnostics = run_diagnostics()
        return jsonify({"success": True, "diagnostics": diagnostics})
    except Exception as e:
        logger.exception(f"Error running diagnostics: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/update_wifi", methods=["POST"])
def update_wifi():
    """Update Wi-Fi configuration"""
    try:
        new_ssid = request.form.get("ssid", "").strip()
        new_password = request.form.get("password", "").strip()

        if not new_ssid or not new_password:
            flash("Both SSID and password are required", "error")
            return redirect("/")

        if write_config(new_ssid, new_password):
            logger.info(f"Wi-Fi config updated: SSID={new_ssid}")
            flash("Wi-Fi configuration updated successfully", "success")
        else:
            flash("Failed to update configuration", "error")

    except Exception as e:
        logger.error(f"Error updating Wi-Fi config: {e}")
        flash(f"Error updating configuration: {e}", "error")

    return redirect("/")


@app.route("/shutdown", methods=["POST"])
def shutdown():
    """Graceful shutdown - stop all personas"""
    try:
        if not persona_manager:
            return jsonify({"success": False, "error": "PersonaManager not initialized"}), 500
        logger.info("Shutdown requested - stopping all personas")
        results = persona_manager.cleanup_all()
        return jsonify({
            "success": True,
            "message": "All personas stopped",
            "results": results
        })
    except Exception as e:
        logger.exception(f"Error during shutdown: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# Error handler for debugging
@app.errorhandler(500)
def internal_error(error):
    logger.exception("Internal server error occurred")
    return jsonify({"success": False, "error": "Internal server error. Check logs for details."}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception(f"Unhandled exception: {e}")
    return jsonify({"success": False, "error": str(e)}), 500

@app.route("/debug")
def debug_info():
    """Debug endpoint to check application state"""
    try:
        # Check Docker socket
        docker_sock_accessible = False
        docker_sock_perms = "N/A"
        try:
            if os.path.exists("/var/run/docker.sock"):
                docker_sock_perms = oct(os.stat("/var/run/docker.sock").st_mode)[-3:]
                # Try to connect
                import docker
                test_client = docker.from_env()
                test_client.ping()
                docker_sock_accessible = True
        except Exception as e:
            docker_error = str(e)
        
        info = {
            "base_dir": BASE_DIR,
            "template_dir": template_dir,
            "static_dir": static_dir,
            "template_exists": os.path.exists(template_dir),
            "static_exists": os.path.exists(static_dir),
            "template_files": os.listdir(template_dir) if os.path.exists(template_dir) else [],
            "static_files": os.listdir(static_dir) if os.path.exists(static_dir) else [],
            "persona_manager_initialized": persona_manager is not None,
            "interface_manager_initialized": interface_manager is not None,
            "config_file_exists": os.path.exists(CONFIG_FILE),
            "log_dir_exists": os.path.exists(LOG_DIR),
            "docker_sock_exists": os.path.exists("/var/run/docker.sock"),
            "docker_sock_permissions": docker_sock_perms,
            "docker_sock_accessible": docker_sock_accessible,
            "docker_error": docker_error if 'docker_error' in locals() else None,
            "current_user": os.getuid(),
            "current_gid": os.getgid(),
        }
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500

if __name__ == "__main__":
    logger.info(f"Wi-Fi Dashboard Manager v{VERSION} starting")
    logger.info(f"BASE_DIR: {BASE_DIR}")
    logger.info(f"Template dir: {template_dir}")
    logger.info(f"Static dir: {static_dir}")
    logger.info(f"Templates exist: {os.path.exists(template_dir)}")
    logger.info(f"Static exists: {os.path.exists(static_dir)}")
    app.run(host="0.0.0.0", port=5000, debug=False)
