/**
 * Adobe Illustrator MCP Plugin
 * 
 * Connects to proxy server and executes JavaScript scripts from MCP.
 */

// WebSocket connection
let ws = null;
let reconnectInterval = null;
const PROXY_WS_URL = 'ws://localhost:8081';

// UI Elements
let connectionStatus = null;
let logArea = null;

/**
 * Initialize the plugin panel
 */
function setupPanel(panel) {
    const container = document.createElement('div');
    container.style.padding = '10px';
    container.style.fontFamily = 'Adobe Clean, sans-serif';

    const title = document.createElement('h3');
    title.textContent = 'MCP Control';
    title.style.margin = '0 0 10px 0';
    container.appendChild(title);

    connectionStatus = document.createElement('div');
    connectionStatus.innerHTML = '<span style="color: orange;">⏳ Connecting...</span>';
    container.appendChild(connectionStatus);

    const connectBtn = document.createElement('button');
    connectBtn.textContent = 'Reconnect';
    connectBtn.style.margin = '10px 0';
    connectBtn.style.width = '100%';
    connectBtn.onclick = connect;
    container.appendChild(connectBtn);

    const logLabel = document.createElement('div');
    logLabel.textContent = 'Log:';
    logLabel.style.marginTop = '10px';
    container.appendChild(logLabel);

    logArea = document.createElement('div');
    logArea.style.cssText = 'height:150px;overflow:auto;background:#1e1e1e;color:#c0c0c0;padding:8px;font-size:11px;font-family:monospace;border-radius:4px;';
    container.appendChild(logArea);

    panel.appendChild(container);
    connect();
}

function log(msg, type = 'info') {
    if (!logArea) return;
    const color = type === 'error' ? '#ff6b6b' : type === 'success' ? '#69db7c' : '#c0c0c0';
    const time = new Date().toLocaleTimeString();
    const entry = document.createElement('div');
    entry.innerHTML = `<span style="color:#666">[${time}]</span> <span style="color:${color}">${msg}</span>`;
    logArea.appendChild(entry);
    logArea.scrollTop = logArea.scrollHeight;
    while (logArea.children.length > 50) logArea.removeChild(logArea.firstChild);
}

function updateStatus(connected) {
    if (!connectionStatus) return;
    connectionStatus.innerHTML = connected
        ? '<span style="color:#69db7c">✅ Connected</span>'
        : '<span style="color:#ff6b6b">❌ Disconnected</span>';
}

function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        log('Already connected');
        return;
    }

    log(`Connecting to ${PROXY_WS_URL}...`);

    try {
        ws = new WebSocket(PROXY_WS_URL);

        ws.onopen = () => {
            log('Connected to proxy', 'success');
            updateStatus(true);
            if (reconnectInterval) {
                clearInterval(reconnectInterval);
                reconnectInterval = null;
            }
        };

        ws.onmessage = async (event) => {
            try {
                const message = JSON.parse(event.data);
                log(`Executing script (id: ${message.id})...`);

                // Execute the script in Illustrator
                let result;
                try {
                    // Use eval to execute the script
                    result = eval(message.script);
                    log('Script executed', 'success');
                } catch (e) {
                    result = JSON.stringify({ error: e.message });
                    log(`Error: ${e.message}`, 'error');
                }

                // Send response
                const response = {
                    id: message.id,
                    result: result
                };
                ws.send(JSON.stringify(response));

            } catch (error) {
                log(`Error: ${error.message}`, 'error');
            }
        };

        ws.onclose = () => {
            log('Disconnected');
            updateStatus(false);
            if (!reconnectInterval) {
                reconnectInterval = setInterval(() => {
                    if (!ws || ws.readyState !== WebSocket.OPEN) {
                        log('Reconnecting...');
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
    }
}

// UXP entrypoints setup for manifest v4
const { entrypoints } = require("uxp");

entrypoints.setup({
    panels: {
        "com.illustrator.mcp.panel": {
            create(rootNode) {
                setupPanel(rootNode);
            },
        },
    },
});
