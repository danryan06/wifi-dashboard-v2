"""
Flask Application for Wi-Fi Dashboard Manager
Updated to use Docker SDK instead of systemd/subprocess
"""

from flask import Flask, render_template, request, redirect, jsonify, flash, send_from_directory
import os
import logging
import time
import json
from datetime import datetime
import threading
import psutil
from .manager_logic import PersonaManager
from .interface_manager import InterfaceManager

app = Flask(__name__)
app.secret_key = 'wifi-test-dashboard-secret-key'

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "configs", "ssid.conf")
SETTINGS_FILE = os.path.join(BASE_DIR, "configs", "settings.conf")
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATS_DIR = os.path.join(BASE_DIR, "stats")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(STATS_DIR, exist_ok=True)

# Initialize managers
persona_manager = PersonaManager()
interface_manager = InterfaceManager()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "manager.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
    ssid, _ = read_config()
    return render_template("dashboard.html", ssid=ssid)


@app.route("/static/<path:filename>")
def static_files(filename):
    """Serve static files"""
    import os
    static_dir = os.path.join(BASE_DIR, "manager", "static")
    return send_from_directory(static_dir, filename)


@app.route("/status")
def status():
    """API endpoint for status information"""
    try:
        ssid, password = read_config()
        
        # Get persona status
        personas = persona_manager.list_personas()
        
        # Get available interfaces
        interfaces = interface_manager.list_available_interfaces()
        
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
            "success": True
        })
    except Exception as e:
        logger.error(f"Error in status endpoint: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas", methods=["GET"])
def api_list_personas():
    """List all persona containers"""
    try:
        personas = persona_manager.list_personas()
        return jsonify({"success": True, "personas": personas})
    except Exception as e:
        logger.error(f"Error listing personas: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/personas", methods=["POST"])
def api_start_persona():
    """Start a new persona container"""
    try:
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
            if not ssid or not password:
                return jsonify({"success": False, "error": "SSID and password required"}), 400
        
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
        tail = int(request.args.get("tail", 100))
        logs = persona_manager.get_persona_logs(container_id, tail=tail)
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        logger.error(f"Error getting logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/logs/aggregate")
def api_aggregate_logs():
    """Get aggregated logs from all persona containers"""
    try:
        personas = persona_manager.list_personas()
        aggregated = {}
        
        for persona in personas:
            if persona['status'] == 'running':
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
        logger.error(f"Error aggregating logs: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/interfaces")
def api_interfaces():
    """Get available network interfaces"""
    try:
        interfaces = interface_manager.list_available_interfaces()
        return jsonify({"success": True, "interfaces": interfaces})
    except Exception as e:
        logger.error(f"Error getting interfaces: {e}")
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
        logger.info("Shutdown requested - stopping all personas")
        results = persona_manager.cleanup_all()
        return jsonify({
            "success": True,
            "message": "All personas stopped",
            "results": results
        })
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info("Wi-Fi Dashboard Manager v2.0 starting")
    app.run(host="0.0.0.0", port=5000, debug=False)
