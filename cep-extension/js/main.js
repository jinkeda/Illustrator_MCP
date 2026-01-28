/**
 * CEP Panel Main JavaScript
 * Handles WebSocket connection to proxy-server and ExtendScript communication
 */

// Configuration
const PROXY_WS_URL = 'ws://localhost:8081';

// Log levels for filtering and display
const LogLevel = {
    DEBUG: 0,
    INFO: 1,
    WARN: 2,
    ERROR: 3
};

// Current log level (can be adjusted for debugging)
let currentLogLevel = LogLevel.INFO;

// Global variables
let ws = null;
let csInterface = null;
let reconnectInterval = null;

/**
 * Format command parameters for logging
 * @param {object} params - Command parameters
 * @returns {string} Formatted parameter string
 */
function formatParams(params) {
    if (!params || Object.keys(params).length === 0) {
        return '';
    }

    // Abbreviate common parameter names for compact display
    const abbrev = {
        'width': 'w',
        'height': 'h',
        'radius': 'r',
        'outer_radius': 'R',
        'inner_radius': 'r',
        'points': 'pts',
        'pointCount': 'pts',
        'closed': 'cls',
        'sides': 'n',
        'font_size': 'sz',
        'opacity': 'op'
    };

    const parts = [];
    for (const [key, value] of Object.entries(params)) {
        const k = abbrev[key] || key;
        // Format numbers to max 1 decimal place
        const v = typeof value === 'number' ?
            (Number.isInteger(value) ? value : value.toFixed(1)) : value;
        parts.push(`${k}:${v}`);
    }

    return parts.join(' ');
}

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
    log(`Connecting to ${PROXY_WS_URL}...`, 'info');

    try {
        ws = new WebSocket(PROXY_WS_URL);

        ws.onopen = () => {
            log('✓ Connected to MCP server!', 'success');
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

                // Log with command context if available (hybrid protocol)
                if (message.command) {
                    const cmd = message.command;
                    // Show command type (now contains description or script preview)
                    const cmdType = cmd.type || 'script';
                    // Truncate long descriptions for display
                    const displayType = cmdType.length > 50 ? cmdType.substring(0, 47) + '...' : cmdType;
                    log(`▶ ${displayType}`, 'info');
                } else {
                    log(`Received script (id: ${message.id})`, 'info');
                }

                // Execute script via ExtendScript
                executeScript(message.id, message.script, message.command);

            } catch (error) {
                log(`Parse error: ${error.message}`, 'error');
            }
        };

        ws.onclose = (event) => {
            log(`Disconnected (code: ${event.code})`, 'warning');
            updateStatus('disconnected');
            updateButton('Connect');

            // Auto-reconnect after 3 seconds (faster retry)
            if (!reconnectInterval) {
                log('Will retry connection in 3 seconds...', 'info');
                reconnectInterval = setInterval(() => {
                    if (!ws || ws.readyState !== WebSocket.OPEN) {
                        log('Retrying connection...', 'info');
                        connect();
                    }
                }, 3000);
            }
        };

        ws.onerror = (error) => {
            log(`Connection error - is MCP server running?`, 'error');
            log(`Ensure Claude Desktop is running or run: python -m illustrator_mcp.server`, 'info');
        };

    } catch (error) {
        log(`Fatal error: ${error.message}`, 'error');
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
 * @param {number} id - Request ID
 * @param {string} script - JavaScript/ExtendScript code to execute
 * @param {object} command - Optional command metadata for logging
 */
function executeScript(id, script, command = null) {
    // Get command type (now contains description or script preview)
    const commandType = command ? (command.type || 'script') : 'raw_script';
    // Truncate for display
    const displayType = commandType.length > 35 ? commandType.substring(0, 32) + '...' : commandType;
    const startTime = Date.now();

    // Escape the script for passing to ExtendScript
    const escapedScript = script
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');

    // Call ExtendScript host function
    csInterface.evalScript(`executeScript('${escapedScript}')`, (result) => {
        const duration = Date.now() - startTime;

        // Log with command context - show the descriptive type
        log(`✓ ${displayType} (${duration}ms)`, 'success');

        // Send response back with command info
        const response = {
            id: id,
            command: commandType,
            result: result,
            duration: duration
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
 * Log message to panel with level support
 * @param {string} message - Message to log
 * @param {string} type - Log type: 'debug', 'info', 'success', 'warning', 'error'
 */
function log(message, type = 'info') {
    // Map type to log level for filtering
    const levelMap = {
        'debug': LogLevel.DEBUG,
        'info': LogLevel.INFO,
        'success': LogLevel.INFO,
        'warning': LogLevel.WARN,
        'error': LogLevel.ERROR
    };

    const messageLevel = levelMap[type] ?? LogLevel.INFO;

    // Filter messages below current log level
    if (messageLevel < currentLogLevel) {
        return;
    }

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

/**
 * Set the log level for filtering
 * @param {number} level - LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, or LogLevel.ERROR
 */
function setLogLevel(level) {
    currentLogLevel = level;
    log(`Log level set to ${Object.keys(LogLevel).find(k => LogLevel[k] === level)}`, 'info');
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);
