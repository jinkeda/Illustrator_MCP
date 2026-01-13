/**
 * CEP Panel Main JavaScript
 * Handles WebSocket connection to proxy-server and ExtendScript communication
 */

// Configuration
const PROXY_WS_URL = 'ws://localhost:8081';

// Global variables
let ws = null;
let csInterface = null;
let reconnectInterval = null;

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);

function init() {
    // Initialize CSInterface
    csInterface = new CSInterface();

    // Set up UI event handlers
    document.getElementById('connectBtn').addEventListener('click', toggleConnection);

    // Log startup
    log('Panel initialized', 'info');
    log(`Target: ${PROXY_WS_URL}`, 'info');

    // Auto-connect on startup
    connect();
}

/**
 * Toggle connection state
 */
function toggleConnection() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        disconnect();
    } else {
        connect();
    }
}

/**
 * Connect to proxy server
 */
function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        log('Already connected', 'warning');
        return;
    }

    updateStatus('connecting');
    log('Connecting...', 'info');

    try {
        ws = new WebSocket(PROXY_WS_URL);

        ws.onopen = () => {
            log('Connected to proxy server', 'success');
            updateStatus('connected');
            updateButton('Disconnect');

            // Clear reconnect interval if exists
            if (reconnectInterval) {
                clearInterval(reconnectInterval);
                reconnectInterval = null;
            }
        };

        ws.onmessage = async (event) => {
            try {
                const message = JSON.parse(event.data);
                log(`Received script (id: ${message.id})`, 'info');

                // Execute script via ExtendScript
                executeScript(message.id, message.script);

            } catch (error) {
                log(`Parse error: ${error.message}`, 'error');
            }
        };

        ws.onclose = () => {
            log('Disconnected', 'warning');
            updateStatus('disconnected');
            updateButton('Connect');

            // Auto-reconnect after 5 seconds
            if (!reconnectInterval) {
                reconnectInterval = setInterval(() => {
                    if (!ws || ws.readyState !== WebSocket.OPEN) {
                        log('Attempting reconnect...', 'info');
                        connect();
                    }
                }, 5000);
            }
        };

        ws.onerror = (error) => {
            log('Connection error', 'error');
        };

    } catch (error) {
        log(`Error: ${error.message}`, 'error');
        updateStatus('disconnected');
    }
}

/**
 * Disconnect from proxy server
 */
function disconnect() {
    if (reconnectInterval) {
        clearInterval(reconnectInterval);
        reconnectInterval = null;
    }

    if (ws) {
        ws.close();
        ws = null;
    }

    log('Disconnected manually', 'info');
    updateStatus('disconnected');
    updateButton('Connect');
}

/**
 * Execute script in Illustrator via ExtendScript
 */
function executeScript(id, script) {
    // Escape the script for passing to ExtendScript
    const escapedScript = script
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');

    // Call ExtendScript host function
    csInterface.evalScript(`executeScript('${escapedScript}')`, (result) => {
        log(`Script ${id} executed`, 'success');

        // Send response back to proxy
        const response = {
            id: id,
            result: result
        };

        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(response));
        } else {
            log('Cannot send response - not connected', 'error');
        }
    });
}

/**
 * Update connection status display
 */
function updateStatus(status) {
    const statusEl = document.getElementById('status');
    statusEl.className = 'status ' + status;

    const statusText = {
        'connected': 'Connected',
        'disconnected': 'Disconnected',
        'connecting': 'Connecting...'
    };

    statusEl.querySelector('.status-text').textContent = statusText[status] || status;
}

/**
 * Update button text
 */
function updateButton(text) {
    document.getElementById('connectBtn').textContent = text;
}

/**
 * Log message to panel
 */
function log(message, type = 'info') {
    const logArea = document.getElementById('logArea');
    const time = new Date().toLocaleTimeString();

    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">[${time}]</span> <span class="log-${type}">${message}</span>`;

    logArea.appendChild(entry);
    logArea.scrollTop = logArea.scrollHeight;

    // Keep only last 100 entries
    while (logArea.children.length > 100) {
        logArea.removeChild(logArea.firstChild);
    }
}
