/**
 * Adobe Illustrator MCP Proxy Server
 * 
 * Configuration is loaded from environment variables or .env file.
 */

const express = require('express');
const { WebSocketServer, WebSocket } = require('ws');
const fs = require('fs');
const path = require('path');

// Load .env file if exists
function loadEnv() {
    const envPath = path.join(__dirname, '..', '.env');
    if (fs.existsSync(envPath)) {
        const content = fs.readFileSync(envPath, 'utf8');
        content.split('\n').forEach(line => {
            line = line.trim();
            if (line && !line.startsWith('#') && line.includes('=')) {
                const [key, ...valueParts] = line.split('=');
                const value = valueParts.join('=').trim().replace(/^["']|["']$/g, '');
                if (!process.env[key.trim()]) {
                    process.env[key.trim()] = value;
                }
            }
        });
    }
}

loadEnv();

// Configuration from environment
const HTTP_PORT = parseInt(process.env.HTTP_PORT || '8080', 10);
const WS_PORT = parseInt(process.env.WS_PORT || '8081', 10);

// Express app for HTTP API
const app = express();
app.use(express.json());

// Track connected Illustrator plugin
let illustratorClient = null;
let pendingRequests = new Map();
let requestId = 0;

// WebSocket server for Illustrator CEP panel
const wss = new WebSocketServer({ port: WS_PORT });

console.log(`[Proxy] WebSocket server listening on port ${WS_PORT}`);

wss.on('connection', (ws) => {
    console.log('[Proxy] Illustrator CEP panel connected');
    illustratorClient = ws;

    ws.on('message', (data) => {
        try {
            const message = JSON.parse(data.toString());
            console.log('[Proxy] Received from Illustrator:', JSON.stringify(message).substring(0, 200));

            if (message.id && pendingRequests.has(message.id)) {
                const { resolve } = pendingRequests.get(message.id);
                pendingRequests.delete(message.id);
                resolve(message);
            }
        } catch (error) {
            console.error('[Proxy] Error parsing message:', error);
        }
    });

    ws.on('close', () => {
        console.log('[Proxy] Illustrator disconnected');
        if (illustratorClient === ws) {
            illustratorClient = null;
        }

        for (const [id, { reject }] of pendingRequests) {
            reject(new Error('Illustrator disconnected'));
            pendingRequests.delete(id);
        }
    });

    ws.on('error', (error) => {
        console.error('[Proxy] WebSocket error:', error);
    });
});

/**
 * Send a script to Illustrator and wait for response
 */
function executeInIllustrator(script, timeout = 30000) {
    return new Promise((resolve, reject) => {
        if (!illustratorClient || illustratorClient.readyState !== WebSocket.OPEN) {
            reject(new Error('Illustrator is not connected. Load the CEP panel first.'));
            return;
        }

        const id = ++requestId;
        const message = { id, script };

        pendingRequests.set(id, { resolve, reject });

        const timeoutId = setTimeout(() => {
            if (pendingRequests.has(id)) {
                pendingRequests.delete(id);
                reject(new Error(`Timeout after ${timeout}ms`));
            }
        }, timeout);

        try {
            illustratorClient.send(JSON.stringify(message));
            console.log('[Proxy] Sent script to Illustrator (id:', id, ')');
        } catch (error) {
            clearTimeout(timeoutId);
            pendingRequests.delete(id);
            reject(error);
        }

        // Update resolve to clear timeout
        const originalResolve = pendingRequests.get(id).resolve;
        pendingRequests.set(id, {
            resolve: (value) => {
                clearTimeout(timeoutId);
                originalResolve(value);
            },
            reject: pendingRequests.get(id).reject
        });
    });
}

// HTTP endpoints

app.get('/status', (req, res) => {
    res.json({
        connected: illustratorClient !== null && illustratorClient.readyState === WebSocket.OPEN,
        pendingRequests: pendingRequests.size,
        config: { httpPort: HTTP_PORT, wsPort: WS_PORT }
    });
});

app.post('/execute', async (req, res) => {
    const { script } = req.body;

    if (!script) {
        return res.status(400).json({ error: 'Script is required' });
    }

    try {
        const result = await executeInIllustrator(script);
        res.json(result);
    } catch (error) {
        console.error('[Proxy] Execute error:', error.message);
        res.status(500).json({ error: error.message });
    }
});

// Start HTTP server
app.listen(HTTP_PORT, () => {
    console.log(`[Proxy] HTTP server listening on port ${HTTP_PORT}`);
    console.log('');
    console.log('Configuration:');
    console.log(`  HTTP_PORT: ${HTTP_PORT}`);
    console.log(`  WS_PORT: ${WS_PORT}`);
    console.log('');
    console.log('To customize, create a .env file in the project root.');
    console.log('');
    console.log('Waiting for Illustrator connection...');
});
