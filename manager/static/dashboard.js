// Wi-Fi Dashboard v2.0 - JavaScript
let currentData = {};
let refreshInterval;
let refreshPaused = false;
let currentLogName = 'manager';
let currentLogContainerId = null;
let autoScrollEnabled = false;
let logStreamInterval = null;

// Tab switching
document.querySelectorAll(".tab").forEach(tab => {
    tab.onclick = () => switchTab(tab.dataset.tab);
});

function switchTab(tabName) {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelector(`[data-tab="${tabName}"]`).classList.add("active");
    const sections = ["status", "personas", "hardware", "diagnostics", "wifi", "logs", "controls"];
    sections.forEach(section => {
        const el = document.getElementById(section);
        if (el) el.classList.toggle("hidden", section !== tabName);
    });
    
    if (tabName === 'personas') {
        updatePersonas();
    } else if (tabName === 'hardware') {
        updateHardwareView();
    } else if (tabName === 'logs') {
        loadCurrentLog();
    } else if (tabName === 'diagnostics') {
        refreshDiagnostics();
    }
}

// Data refresh
async function refreshData() {
    if (refreshPaused) return;
    
    try {
        const response = await fetch('/status');
        if (!response.ok) throw new Error('Failed to fetch status');
        currentData = await response.json();
        updateUI(currentData);
        updateStatusPill('✅ Connected', 'var(--success)');
    } catch (error) {
        console.error('Error refreshing data:', error);
        updateStatusPill('❌ Connection Error', 'var(--error)');
    }
}

function updateUI(data) {
    // Update status items
    document.getElementById('current-ssid').textContent = data.ssid || '(not configured)';
    
    // Manager status
    const managerStatus = 'Running'; // Manager container should always be running
    document.getElementById('manager-status').textContent = managerStatus;
    
    // Active personas count
    const activePersonas = (data.personas || []).filter(p => p.status === 'running').length;
    document.getElementById('active-personas').textContent = `${activePersonas} running`;
    
    // Available interfaces
    const availableInterfaces = Object.keys(data.interfaces || {}).length;
    document.getElementById('available-interfaces').textContent = `${availableInterfaces} detected`;
    
    // Update Wi-Fi form if not being edited
    const ssidInput = document.getElementById('ssid');
    const passwordInput = document.getElementById('password');
    if (ssidInput && document.activeElement !== ssidInput) {
        ssidInput.value = data.ssid || '';
    }
    // Don't update password field (security - it's masked anyway)
    // Password is checked via password_masked field in currentData
}

// Persona management
async function updatePersonas() {
    try {
        const response = await fetch('/api/personas');
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                displayPersonas(data.personas);
                updateInterfaceDropdown(data.personas);
            }
        }
    } catch (error) {
        console.error('Error updating personas:', error);
    }
}

function displayPersonas(personas) {
    const container = document.getElementById('persona-grid');
    
    if (!personas || personas.length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--muted);">No personas running. Start one above!</div>';
        return;
    }
    
    container.innerHTML = personas.map(persona => {
        const statusClass = persona.status === 'running' ? 'running' : 
                          persona.status === 'exited' ? 'exited' : 'stopped';
        const personaClass = persona.persona_type || 'unknown';
        
        return `
            <div class="persona-card ${personaClass}">
                <div class="persona-header">
                    <div class="persona-type">${persona.persona_type || 'Unknown'} Client</div>
                    <div class="persona-status ${statusClass}">${persona.status}</div>
                </div>
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 0.9em; color: var(--muted); margin-bottom: 4px;">Container</div>
                    <div style="font-family: monospace; font-size: 0.85em;">${persona.name}</div>
                </div>
                ${persona.interface ? `
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 0.9em; color: var(--muted); margin-bottom: 4px;">Interface</div>
                    <div style="font-weight: 600; color: var(--accent);">${persona.interface}</div>
                </div>
                ` : ''}
                ${persona.hostname ? `
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 0.9em; color: var(--muted); margin-bottom: 4px;">Hostname</div>
                    <div style="font-family: monospace; font-size: 0.85em;">${persona.hostname}</div>
                </div>
                ` : ''}
                <div style="display: flex; gap: 8px; margin-top: 16px;">
                    <button onclick="viewPersonaLogs('${persona.id}')" class="secondary" style="flex: 1;">📋 Logs</button>
                    <button onclick="stopPersona('${persona.id}')" class="danger" style="flex: 1;">⏹️ Stop</button>
                </div>
            </div>
        `;
    }).join('');
}

function updateInterfaceDropdown(personas) {
    const select = document.getElementById('persona-interface');
    if (!select) return;
    
    // Preserve current selection
    const currentValue = select.value;
    
    // Get assigned interfaces
    const assignedInterfaces = new Set(
        personas.filter(p => p.status === 'running' && p.interface)
            .map(p => p.interface)
    );
    
    // Get all available interfaces
    fetch('/api/interfaces')
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                select.innerHTML = '<option value="">Select interface...</option>';
                Object.keys(data.interfaces).forEach(iface => {
                    const isAssigned = assignedInterfaces.has(iface);
                    const option = document.createElement('option');
                    option.value = iface;
                    option.textContent = `${iface}${isAssigned ? ' (assigned)' : ''}`;
                    option.disabled = isAssigned;
                    select.appendChild(option);
                });
                // Restore selection if it still exists
                if (currentValue && !assignedInterfaces.has(currentValue)) {
                    select.value = currentValue;
                }
            }
        })
        .catch(err => console.error('Error loading interfaces:', err));
}

// Start persona
document.getElementById('start-persona-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const formData = new FormData(e.target);
    const personaType = formData.get('persona_type');
    const interface = formData.get('interface');
    
    if (!interface) {
        showMessage('Please select an interface', 'error');
        return;
    }
    
    // Get SSID/password from saved server config (not form - form may not reflect saved values)
    // Use currentData which is refreshed from /status endpoint
    const ssid = currentData?.ssid || '';
    // Check if password is configured (password_masked will be non-empty if config exists)
    const hasPassword = currentData?.password_masked && currentData.password_masked.length > 0;
    
    // For wired personas, no Wi-Fi config needed
    if (personaType === 'wired') {
        // Wired personas don't need Wi-Fi config - proceed
    } else if (personaType === 'bad') {
        // Bad personas need SSID but not password (they use wrong password)
        if (!ssid) {
            showMessage('Please configure Wi-Fi SSID first in the Wi-Fi Config tab', 'error');
            return;
        }
    } else if (personaType === 'good') {
        // Good personas need both SSID and password
        // Check if config exists (password_masked indicates config was saved)
        if (!ssid || !hasPassword) {
            showMessage('Please configure Wi-Fi settings first (SSID and password) in the Wi-Fi Config tab', 'error');
            return;
        }
    }
    
    try {
        const response = await fetch('/api/personas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                persona_type: personaType,
                interface: interface,
                // Backend will use saved config if not provided, but we pass SSID for clarity
                ssid: personaType !== 'wired' ? ssid : undefined,
                // Password is handled by backend from saved config
                password: undefined  // Backend reads from config file
            })
        });
        
        const data = await response.json();
        if (data.success) {
            showMessage(data.message, 'success');
            setTimeout(updatePersonas, 2000);
            e.target.reset();
        } else {
            showMessage(data.error || 'Failed to start persona', 'error');
        }
    } catch (error) {
        showMessage(`Error: ${error.message}`, 'error');
    }
});

// Stop persona
async function stopPersona(containerId) {
    if (!confirm('Stop this persona? The interface will be returned to the host.')) return;
    
    try {
        const response = await fetch(`/api/personas/${containerId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        if (data.success) {
            showMessage(data.message, 'success');
            setTimeout(updatePersonas, 1000);
        } else {
            showMessage(data.error || 'Failed to stop persona', 'error');
        }
    } catch (error) {
        showMessage(`Error: ${error.message}`, 'error');
    }
}

// Hardware view
async function updateHardwareView() {
    const container = document.getElementById('hardware-view');
    if (!container) return;
    
    // Show loading state
    container.innerHTML = '<div style="text-align: center; padding: 40px;"><span class="spinner"></span> Loading hardware information...</div>';
    
    try {
        const [interfacesRes, personasRes] = await Promise.all([
            fetch('/api/interfaces'),
            fetch('/api/personas')
        ]);
        
        if (!interfacesRes.ok || !personasRes.ok) {
            throw new Error(`API error: interfaces=${interfacesRes.status}, personas=${personasRes.status}`);
        }
        
        const interfacesData = await interfacesRes.json();
        const personasData = await personasRes.json();
        
        if (interfacesData.success && personasData.success) {
            // Fix: personasData.personas is the array
            displayHardwareView(interfacesData.interfaces || {}, personasData.personas || []);
        } else {
            const errorMsg = interfacesData.error || personasData.error || 'Unknown error';
            container.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error);">Error loading hardware: ${errorMsg}</div>`;
        }
    } catch (error) {
        console.error('Error updating hardware view:', error);
        container.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error);">Error loading hardware: ${error.message}</div>`;
    }
}

function displayHardwareView(interfaces, personas) {
    const container = document.getElementById('hardware-view');
    
    // Create map of interface to persona
    // Fix: personas is already the array, not an object with .personas
    const personaArray = Array.isArray(personas) ? personas : (personas.personas || []);
    const interfaceMap = {};
    personaArray.forEach(p => {
        if (p.interface && p.status === 'running') {
            interfaceMap[p.interface] = p;
        }
    });
    
    if (!interfaces || Object.keys(interfaces).length === 0) {
        container.innerHTML = '<div style="text-align: center; padding: 40px; color: var(--muted);">No interfaces detected</div>';
        return;
    }
    
    container.innerHTML = Object.entries(interfaces).map(([iface, info]) => {
        const persona = interfaceMap[iface];
        const isAssigned = !!persona;
        const cardClass = isAssigned ? 'assigned' : 'available';
        
        return `
            <div class="hardware-card ${cardClass}">
                <div class="hardware-name">${iface.toUpperCase()}</div>
                <div class="hardware-status">
                    ${isAssigned ? `
                        <div style="margin-bottom: 8px;">
                            <strong>Assigned to:</strong> ${persona.persona_type} persona
                        </div>
                        <div style="font-size: 0.85em; color: var(--muted);">
                            Container: ${persona.name.substring(0, 30)}...
                        </div>
                    ` : `
                        <div style="color: var(--muted);">Available for assignment</div>
                    `}
                    <div style="margin-top: 8px; font-size: 0.85em;">
                        Type: ${info.type || 'unknown'}<br>
                        State: ${info.state || 'unknown'}<br>
                        ${info.phy ? `PHY: ${info.phy}` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Log viewing
async function loadCurrentLog() {
    if (currentLogName === 'manager') {
        loadManagerLog();
    } else if (currentLogContainerId) {
        loadPersonaLog(currentLogContainerId);
    }
}

async function loadManagerLog() {
    try {
        showLogLoading();
        const response = await fetch('/api/logs/manager?tail=500');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        
        if (data.success && data.logs && data.logs.length > 0) {
            displayLogContent(data.logs);
        } else if (data.success && (!data.logs || data.logs.length === 0)) {
            const logContent = document.getElementById('log-content');
            logContent.innerHTML = `
                <div style="padding: 20px; text-align: center; color: var(--muted);">
                    <p>No log entries found yet.</p>
                    <p style="margin-top: 10px; font-size: 0.9em;">
                        Logs will appear here as the manager runs.
                    </p>
                    <p style="margin-top: 10px; font-size: 0.85em;">
                        For full logs, run: <code>docker logs wifi-manager -f</code>
                    </p>
                </div>
            `;
        } else {
            showLogError('Failed to load manager logs: ' + (data.error || 'Unknown error'));
        }
    } catch (error) {
        console.error('Error loading manager log:', error);
        showLogError('Error loading manager log: ' + error.message);
    }
}

async function loadPersonaLog(containerId) {
    try {
        showLogLoading();
        const response = await fetch(`/api/personas/${containerId}/logs?tail=200`);
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                displayLogContent(data.logs);
            } else {
                showLogError('Failed to load log: ' + data.error);
            }
        } else {
            showLogError('Log API not available');
        }
    } catch (error) {
        showLogError('Error loading log: ' + error.message);
    }
}

function viewPersonaLogs(containerId) {
    currentLogContainerId = containerId;
    currentLogName = 'persona';
    
    // Switch to logs tab
    switchTab('logs');
    
    // Update log tabs
    updateLogTabs();
    
    // Load logs
    loadPersonaLog(containerId);
}

function updateLogTabs() {
    const tabsContainer = document.getElementById('log-tabs');
    if (!tabsContainer) return;
    
    // Add persona log tab if viewing persona
    if (currentLogContainerId) {
        tabsContainer.innerHTML = `
            <button class="log-tab" data-log="manager" onclick="switchToManagerLog()">📄 Manager</button>
            <button class="log-tab active" data-log="persona">👤 Persona</button>
        `;
    } else {
        tabsContainer.innerHTML = `
            <button class="log-tab active" data-log="manager">📄 Manager</button>
        `;
    }
}

function switchToManagerLog() {
    currentLogName = 'manager';
    currentLogContainerId = null;
    updateLogTabs();
    loadManagerLog();
}

function displayLogContent(logs) {
    const logContent = document.getElementById('log-content');
    if (logs && logs.length > 0) {
        logContent.textContent = logs.join('\n');
        if (autoScrollEnabled) {
            logContent.scrollTop = logContent.scrollHeight;
        }
    } else {
        logContent.textContent = 'No log entries found';
    }
}

function showLogLoading() {
    const logContent = document.getElementById('log-content');
    logContent.innerHTML = '<div class="log-loading"><span class="spinner"></span> Loading logs...</div>';
}

function showLogError(message) {
    const logContent = document.getElementById('log-content');
    logContent.innerHTML = `<div style="text-align: center; padding: 40px; color: var(--error);">⚠️ ${message}</div>`;
}

function refreshCurrentLog() {
    loadCurrentLog();
    showMessage('Log refreshed', 'info');
}

function toggleAutoScroll() {
    autoScrollEnabled = !autoScrollEnabled;
    const btn = document.getElementById('auto-scroll-btn');
    btn.textContent = `🔄 Auto-scroll: ${autoScrollEnabled ? 'On' : 'Off'}`;
    if (autoScrollEnabled) {
        btn.classList.remove('secondary');
        const logContent = document.getElementById('log-content');
        logContent.scrollTop = logContent.scrollHeight;
    } else {
        btn.classList.add('secondary');
    }
}

// System controls
async function stopAllPersonas() {
    if (!confirm('Stop all running personas? All interfaces will be returned to the host.')) return;
    
    try {
        const response = await fetch('/shutdown', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showMessage('All personas stopped', 'success');
            setTimeout(updatePersonas, 2000);
        } else {
            showMessage(data.error || 'Failed to stop personas', 'error');
        }
    } catch (error) {
        showMessage(`Error: ${error.message}`, 'error');
    }
}

async function restartManager() {
    if (!confirm('Restart the manager container? This will temporarily disconnect the dashboard.')) return;
    showMessage('Manager restart not yet implemented', 'info');
}

// Utility functions
function showMessage(message, type = 'info') {
    const container = document.getElementById('flash-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `flash-message ${type}`;
    messageDiv.textContent = message;
    container.appendChild(messageDiv);
    setTimeout(() => {
        if (messageDiv.parentNode) {
            messageDiv.parentNode.removeChild(messageDiv);
        }
    }, 5000);
}

function updateStatusPill(text, color) {
    const pill = document.getElementById('status-pill');
    if (pill) {
        pill.innerHTML = text;
        pill.style.backgroundColor = color;
    }
}

// Diagnostics
async function refreshDiagnostics() {
    const content = document.getElementById('diagnostics-content');
    if (!content) return;
    
    try {
        content.innerHTML = '<div style="text-align: center; padding: 20px;"><span class="spinner"></span> Loading diagnostics...</div>';
        
        const response = await fetch('/api/diagnostics');
        if (!response.ok) throw new Error('Failed to fetch diagnostics');
        const data = await response.json();
        
        if (data.success) {
            displayDiagnostics(data.diagnostics);
        } else {
            content.innerHTML = `<div style="color: var(--error); padding: 20px;">Error: ${data.error || 'Unknown error'}</div>`;
        }
    } catch (error) {
        console.error('Error loading diagnostics:', error);
        content.innerHTML = `<div style="color: var(--error); padding: 20px;">Error loading diagnostics: ${error.message}</div>`;
    }
}

function displayDiagnostics(diag) {
    const content = document.getElementById('diagnostics-content');
    if (!content) return;
    
    let html = '<div style="display: grid; gap: 24px;">';
    
    // Summary
    html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
    html += '<h3 style="margin-top: 0;">📊 Summary</h3>';
    html += `<p><strong>USB Devices:</strong> ${diag.summary.total_usb_devices} total, ${diag.summary.wifi_usb_devices} Wi-Fi adapters</p>`;
    html += `<p><strong>Interfaces Detected:</strong> ${diag.summary.interfaces_detected}</p>`;
    html += `<p><strong>Drivers Loaded:</strong> ${diag.summary.drivers_loaded}</p>`;
    html += `<p><strong>Issues Found:</strong> ${diag.summary.issues_found}</p>`;
    html += `<p><strong>Recommendations:</strong> ${diag.summary.recommendations_count}</p>`;
    html += '</div>';
    
    // USB Wi-Fi Devices
    if (diag.wifi_usb_devices && diag.wifi_usb_devices.length > 0) {
        html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
        html += '<h3 style="margin-top: 0;">🔌 USB Wi-Fi Devices</h3>';
        diag.wifi_usb_devices.forEach(device => {
            const statusColor = device.driver_loaded && device.has_interface ? 'var(--success)' : 'var(--warning)';
            const statusIcon = device.driver_loaded && device.has_interface ? '✅' : '⚠️';
            html += `<div style="margin-bottom: 16px; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 6px; border-left: 4px solid ${statusColor};">`;
            html += `<div style="font-weight: 600; margin-bottom: 8px;">${statusIcon} ${device.device_name}</div>`;
            html += `<div style="font-size: 0.9em; color: var(--muted); margin-bottom: 4px;">Device ID: ${device.device_id}</div>`;
            html += `<div style="font-size: 0.9em;">Expected Driver: <code>${device.expected_driver}</code>`;
            if (device.alt_driver) {
                html += ` or <code>${device.alt_driver}</code>`;
            }
            html += `</div>`;
            html += `<div style="font-size: 0.9em; margin-top: 4px;">`;
            html += `Driver Loaded: ${device.driver_loaded ? '✅ Yes' : '❌ No'}`;
            if (device.driver_name) {
                html += ` (${device.driver_name})`;
            }
            html += ` | Interface: ${device.has_interface ? '✅ Yes' : '❌ No'}`;
            html += `</div>`;
            html += '</div>';
        });
        html += '</div>';
    }
    
    // Issues
    if (diag.issues && diag.issues.length > 0) {
        html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
        html += '<h3 style="margin-top: 0; color: var(--warning);">⚠️ Issues Detected</h3>';
        diag.issues.forEach(issue => {
            const severityColor = issue.severity === 'high' ? 'var(--error)' : 'var(--warning)';
            html += `<div style="margin-bottom: 12px; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 6px; border-left: 4px solid ${severityColor};">`;
            html += `<div style="font-weight: 600; margin-bottom: 4px;">${issue.device || 'System'}</div>`;
            html += `<div style="font-size: 0.9em; color: var(--muted);">${issue.message}</div>`;
            if (issue.expected_driver) {
                html += `<div style="font-size: 0.85em; margin-top: 4px; color: var(--muted);">Expected driver: <code>${issue.expected_driver}</code></div>`;
            }
            html += '</div>';
        });
        html += '</div>';
    }
    
    // Recommendations
    if (diag.recommendations && diag.recommendations.length > 0) {
        html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
        html += '<h3 style="margin-top: 0; color: var(--info);">💡 Recommendations</h3>';
        diag.recommendations.forEach(rec => {
            html += `<div style="margin-bottom: 16px; padding: 12px; background: rgba(255,255,255,0.03); border-radius: 6px;">`;
            html += `<div style="font-weight: 600; margin-bottom: 8px;">${rec.device || 'System'}</div>`;
            html += `<div style="font-size: 0.9em; margin-bottom: 8px;">${rec.message}</div>`;
            if (rec.commands && rec.commands.length > 0) {
                html += '<div style="background: rgba(0,0,0,0.3); padding: 8px; border-radius: 4px; font-family: monospace; font-size: 0.85em; margin-top: 8px;">';
                rec.commands.forEach(cmd => {
                    html += `<div style="margin-bottom: 4px;">${cmd}</div>`;
                });
                html += '</div>';
            }
            if (rec.persistent) {
                html += `<div style="font-size: 0.85em; color: var(--muted); margin-top: 8px;">To make persistent: <code>${rec.persistent}</code></div>`;
            }
            html += '</div>';
        });
        html += '</div>';
    }
    
    // Loaded Drivers
    if (diag.loaded_drivers && diag.loaded_drivers.length > 0) {
        html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
        html += '<h3 style="margin-top: 0;">📦 Loaded Wi-Fi Drivers</h3>';
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px;">';
        diag.loaded_drivers.forEach(driver => {
            html += `<span style="background: var(--success); color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.85em;"><code>${driver}</code></span>`;
        });
        html += '</div></div>';
    }
    
    // Available Interfaces
    if (diag.wifi_interfaces && diag.wifi_interfaces.length > 0) {
        html += '<div style="background: rgba(255,255,255,0.05); padding: 16px; border-radius: 8px;">';
        html += '<h3 style="margin-top: 0;">📡 Available Wi-Fi Interfaces</h3>';
        html += '<div style="display: flex; flex-wrap: wrap; gap: 8px;">';
        diag.wifi_interfaces.forEach(iface => {
            html += `<span style="background: var(--accent); color: white; padding: 4px 12px; border-radius: 12px; font-size: 0.85em;"><code>${iface}</code></span>`;
        });
        html += '</div></div>';
    }
    
    html += '</div>';
    content.innerHTML = html;
}

// Initialize
refreshData();
refreshInterval = setInterval(refreshData, 10000); // 10 second refresh

// Update personas every 5 seconds when on personas tab
setInterval(() => {
    if (!document.getElementById('personas')?.classList.contains('hidden')) {
        updatePersonas();
    }
}, 5000);
