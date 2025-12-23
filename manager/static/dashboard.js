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
    const sections = ["status", "personas", "hardware", "wifi", "logs", "controls"];
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
    if (ssidInput && !document.activeElement === ssidInput) {
        ssidInput.value = data.ssid || '';
    }
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
    
    // Get SSID/password from server config (not form - form may not be saved)
    // The backend will use saved config if not provided, but we check here for better UX
    const ssid = document.getElementById('ssid')?.value;
    const password = document.getElementById('password')?.value;
    
    // For wired personas, no Wi-Fi config needed
    if (personaType === 'wired') {
        // Wired personas don't need Wi-Fi config - proceed
    } else if (personaType === 'bad') {
        // Bad personas need SSID but not password (they use wrong password)
        if (!ssid) {
            showMessage('Please configure Wi-Fi SSID first', 'error');
            return;
        }
    } else if (personaType === 'good') {
        // Good personas need both SSID and password
        if (!ssid || !password) {
            showMessage('Please configure Wi-Fi settings first (SSID and password)', 'error');
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
                ssid: personaType !== 'wired' ? ssid : undefined,
                password: personaType === 'good' ? password : undefined
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

// Initialize
refreshData();
refreshInterval = setInterval(refreshData, 10000); // 10 second refresh

// Update personas every 5 seconds when on personas tab
setInterval(() => {
    if (!document.getElementById('personas')?.classList.contains('hidden')) {
        updatePersonas();
    }
}, 5000);
