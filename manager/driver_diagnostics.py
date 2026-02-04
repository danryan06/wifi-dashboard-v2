"""
Driver Diagnostics: Detects USB Wi-Fi devices and checks if drivers are loaded.
Provides recommendations for missing drivers.
"""

import subprocess
import logging
import re
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Common USB Wi-Fi device IDs and their required drivers
# Format: 'vendor:product' -> {'driver': 'module_name', 'alt_driver': 'alternative', 'name': 'Display Name'}
USB_WIFI_DRIVERS = {
    # Realtek - Most common
    '7392:b811': {'driver': 'rtl8xxxu', 'alt_driver': 'rtl8192cu', 'name': 'Realtek RTL8188EU (Edimax N150)'},
    '0bda:8176': {'driver': 'rtl8192cu', 'name': 'Realtek RTL8192CU'},
    '0bda:8178': {'driver': 'rtl8192cu', 'name': 'Realtek RTL8192CU'},
    '0bda:8179': {'driver': 'rtl8192cu', 'name': 'Realtek RTL8192CU'},
    '0bda:818b': {'driver': 'rtl8192cu', 'name': 'Realtek RTL8192CU'},
    '0bda:8187': {'driver': 'rtl8192cu', 'name': 'Realtek RTL8192CU'},
    '0bda:8812': {'driver': 'rtl8812au', 'name': 'Realtek RTL8812AU'},
    '0bda:8813': {'driver': 'rtl8812au', 'name': 'Realtek RTL8812AU'},
    '0bda:8821': {'driver': 'rtl8821au', 'name': 'Realtek RTL8821AU'},
    '0bda:0821': {'driver': 'rtl8xxxu', 'name': 'Realtek RTL8821AU'},
    '0bda:0823': {'driver': 'rtl8xxxu', 'name': 'Realtek RTL8822BU'},
    # Ralink/MediaTek
    '148f:5370': {'driver': 'rt2800usb', 'name': 'Ralink RT5370'},
    '148f:5572': {'driver': 'rt2800usb', 'name': 'Ralink RT5572'},
    '148f:7601': {'driver': 'mt7601u', 'name': 'MediaTek MT7601U'},
    # Atheros
    '0cf3:9271': {'driver': 'ath9k_htc', 'name': 'Atheros AR9271'},
    '0cf3:7015': {'driver': 'ath9k_htc', 'name': 'Atheros AR7015'},
    # Broadcom
    '0a5c:bd27': {'driver': 'brcmfmac', 'name': 'Broadcom BCM43236'},
    # Intel
    '8086:08b1': {'driver': 'iwlwifi', 'name': 'Intel Wireless'},
    '8086:08b2': {'driver': 'iwlwifi', 'name': 'Intel Wireless'},
}


def get_usb_devices() -> List[Dict]:
    """Get list of USB devices using lsusb"""
    devices = []
    try:
        result = subprocess.run(
            ['lsusb'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        for line in result.stdout.split('\n'):
            if 'ID' in line:
                # Parse: "Bus 001 Device 003: ID 7392:b811 Edimax Technology Co., Ltd Edimax N150 Adapter"
                match = re.search(r'ID\s+([0-9a-f]{4}):([0-9a-f]{4})', line)
                if match:
                    vendor_id = match.group(1)
                    product_id = match.group(2)
                    device_id = f"{vendor_id}:{product_id}"
                    
                    # Extract device name
                    parts = line.split(':', 1)
                    name = parts[1].strip() if len(parts) > 1 else 'Unknown device'
                    
                    devices.append({
                        'id': device_id,
                        'vendor_id': vendor_id,
                        'product_id': product_id,
                        'name': name,
                        'full_line': line
                    })
    except Exception as e:
        logger.error(f"Error getting USB devices: {e}")
    
    return devices


def get_loaded_drivers() -> List[str]:
    """Get list of loaded Wi-Fi driver modules"""
    drivers = []
    try:
        result = subprocess.run(
            ['lsmod'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Common Wi-Fi driver patterns
        wifi_driver_patterns = [
            'rtl', 'ath', 'iwl', 'brcm', 'mt76', 'mt792', 'rt28', 'rt2x00',
            'wl', 'b43', 'b43legacy', 'zd1211', 'hostap', 'mac80211', 'cfg80211'
        ]
        
        for line in result.stdout.split('\n'):
            module_name = line.split()[0] if line.split() else ''
            if any(pattern in module_name.lower() for pattern in wifi_driver_patterns):
                if module_name not in drivers:
                    drivers.append(module_name)
    except Exception as e:
        logger.error(f"Error getting loaded drivers: {e}")
    
    return drivers


def check_driver_for_device(device_id: str) -> Optional[Dict]:
    """Check if a driver is bound to a specific USB device"""
    try:
        result = subprocess.run(
            ['lsusb', '-t'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Look for the device in the tree and check Driver field
        for line in result.stdout.split('\n'):
            if device_id.split(':')[1] in line or device_id in line:
                # Check if driver is mentioned
                if 'Driver=' in line:
                    driver_match = re.search(r'Driver=(\S+)', line)
                    if driver_match:
                        driver = driver_match.group(1)
                        if driver and driver != '(none)':
                            return {'driver': driver, 'bound': True}
        
        # Also try lsusb -v
        result = subprocess.run(
            ['lsusb', '-v', '-d', device_id],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        # Check if driver is bound
        if 'Driver=' in result.stdout:
            for line in result.stdout.split('\n'):
                if 'Driver=' in line:
                    driver = line.split('Driver=')[1].strip()
                    if driver and driver != '(none)':
                        return {'driver': driver, 'bound': True}
        
        return {'driver': None, 'bound': False}
    except Exception as e:
        logger.debug(f"Error checking driver for {device_id}: {e}")
        return None


def get_available_interfaces() -> List[str]:
    """Get list of available Wi-Fi interfaces"""
    interfaces = []
    try:
        result = subprocess.run(
            ['iw', 'dev'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        for line in result.stdout.split('\n'):
            if 'Interface' in line:
                parts = line.split()
                if len(parts) >= 2:
                    interfaces.append(parts[1])
    except Exception as e:
        logger.debug(f"Error getting interfaces: {e}")
    
    return interfaces


def check_driver_module_exists(driver_name: str) -> bool:
    """Check if a driver module exists (can be loaded)"""
    try:
        result = subprocess.run(
            ['modinfo', driver_name],
            capture_output=True,
            text=True,
            timeout=3
        )
        return result.returncode == 0
    except Exception:
        return False


def run_diagnostics() -> Dict:
    """
    Run comprehensive driver diagnostics.
    Returns dict with USB devices, drivers, interfaces, and recommendations.
    """
    diagnostics = {
        'usb_devices': [],
        'wifi_interfaces': [],
        'loaded_drivers': [],
        'wifi_usb_devices': [],
        'issues': [],
        'recommendations': []
    }
    
    # Get USB devices
    usb_devices = get_usb_devices()
    diagnostics['usb_devices'] = usb_devices
    
    # Get loaded drivers
    loaded_drivers = get_loaded_drivers()
    diagnostics['loaded_drivers'] = loaded_drivers
    
    # Get available interfaces
    wifi_interfaces = get_available_interfaces()
    diagnostics['wifi_interfaces'] = wifi_interfaces
    
    # Analyze USB Wi-Fi devices
    wifi_usb_devices = []
    for device in usb_devices:
        device_id = device['id']
        
        # Check if it's a known Wi-Fi device
        if device_id in USB_WIFI_DRIVERS:
            wifi_info = USB_WIFI_DRIVERS[device_id]
            driver_info = check_driver_for_device(device_id)
            
            expected_driver = wifi_info.get('driver')
            alt_driver = wifi_info.get('alt_driver')
            
            device_status = {
                'device': device,
                'expected_driver': expected_driver,
                'alt_driver': alt_driver,
                'device_name': wifi_info.get('name', device['name']),
                'driver_loaded': driver_info['bound'] if driver_info else False,
                'driver_name': driver_info['driver'] if driver_info else None,
                'has_interface': False
            }
            
            # Check if interface exists (approximate - count interfaces)
            # If we have more interfaces than devices analyzed, assume they're working
            device_status['has_interface'] = len(wifi_interfaces) > len(wifi_usb_devices)
            
            wifi_usb_devices.append(device_status)
            
            # Check for issues
            if not device_status['driver_loaded']:
                # Check if driver module exists
                driver_exists = expected_driver in loaded_drivers or (alt_driver and alt_driver in loaded_drivers)
                driver_module_exists = check_driver_module_exists(expected_driver) or (alt_driver and check_driver_module_exists(alt_driver))
                
                if not driver_exists and driver_module_exists:
                    # Driver module exists but not loaded
                    diagnostics['issues'].append({
                        'type': 'driver_not_loaded',
                        'severity': 'high',
                        'device': device_status['device_name'],
                        'device_id': device_id,
                        'expected_driver': expected_driver,
                        'alt_driver': alt_driver,
                        'message': f"USB Wi-Fi device {device_status['device_name']} detected but driver not loaded"
                    })
                    
                    # Generate recommendation
                    drivers_to_try = [expected_driver]
                    if alt_driver:
                        drivers_to_try.append(alt_driver)
                    
                    diagnostics['recommendations'].append({
                        'type': 'load_driver',
                        'device': device_status['device_name'],
                        'device_id': device_id,
                        'commands': [f"sudo modprobe {driver}" for driver in drivers_to_try],
                        'persistent': f"Add to /etc/modules: echo '{drivers_to_try[0]}' | sudo tee -a /etc/modules",
                        'message': f"Load driver for {device_status['device_name']}: sudo modprobe {expected_driver}"
                    })
                elif not driver_module_exists:
                    # Driver module doesn't exist - may need installation
                    diagnostics['issues'].append({
                        'type': 'driver_missing',
                        'severity': 'high',
                        'device': device_status['device_name'],
                        'device_id': device_id,
                        'expected_driver': expected_driver,
                        'message': f"USB Wi-Fi device {device_status['device_name']} detected but driver module not found"
                    })
                    
                    diagnostics['recommendations'].append({
                        'type': 'install_driver',
                        'device': device_status['device_name'],
                        'device_id': device_id,
                        'expected_driver': expected_driver,
                        'message': f"Driver module {expected_driver} not found. May need to install firmware or compile driver.",
                        'suggestions': [
                            f"Check if firmware package exists: apt-cache search {expected_driver}",
                            f"Install firmware: sudo apt-get install firmware-realtek",
                            f"Or check kernel modules: find /lib/modules/$(uname -r) -name '*{expected_driver}*'"
                        ]
                    })
                else:
                    # Driver loaded but not bound
                    diagnostics['issues'].append({
                        'type': 'driver_not_bound',
                        'severity': 'medium',
                        'device': device_status['device_name'],
                        'device_id': device_id,
                        'message': f"Driver module loaded but not bound to device"
                    })
            elif not device_status['has_interface']:
                # Driver loaded but no interface
                diagnostics['issues'].append({
                    'type': 'no_interface',
                    'severity': 'medium',
                    'device': device_status['device_name'],
                    'device_id': device_id,
                    'message': f"Driver loaded but no network interface detected"
                })
    
    diagnostics['wifi_usb_devices'] = wifi_usb_devices
    
    # Summary
    diagnostics['summary'] = {
        'total_usb_devices': len(usb_devices),
        'wifi_usb_devices': len(wifi_usb_devices),
        'interfaces_detected': len(wifi_interfaces),
        'drivers_loaded': len(loaded_drivers),
        'issues_found': len(diagnostics['issues']),
        'recommendations_count': len(diagnostics['recommendations'])
    }
    
    return diagnostics
