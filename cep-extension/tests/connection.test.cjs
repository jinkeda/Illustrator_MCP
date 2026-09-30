const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { pathToFileURL } = require('node:url');

// Use the existing compiler and Node's test runner; no new runtime dependencies.
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'illustrator-mcp-connection-'));
after(() => fs.rmSync(scratch, { recursive: true, force: true }));
execFileSync(process.execPath, [require.resolve('typescript/bin/tsc'),
    '--target', 'ES2020', '--module', 'commonjs', '--strict', '--skipLibCheck',
    '--outDir', scratch,
    'src/connection/EndpointConfig.ts', 'src/connection/ConnectionController.ts',
], { cwd: path.resolve(__dirname, '..'), stdio: 'pipe' });
const { DEFAULT_MCP_ENDPOINT, loadEndpointConfig, parseEndpointConfig } = require(path.join(scratch, 'EndpointConfig.js'));
const { ConnectionController, selectConnectionControl } = require(path.join(scratch, 'ConnectionController.js'));

function runtime(directory, modules = {}) {
    return {
        __adobe_cep__: { getSystemPath: type => {
            assert.equal(type, 'extension');
            return directory;
        } },
        cep_node: { require: name => modules[name] || require(name) },
    };
}
const config = endpoint => ({ endpoint, source: 'test/connection.json' });

test('browser previews do not require Node and keep the default', () => {
    assert.equal(loadEndpointConfig({ require: () => assert.fail('Node accessed') }).endpoint, DEFAULT_MCP_ENDPOINT);
});

test('missing file defaults; changing the file takes effect on the next load', () => {
    const directory = fs.mkdtempSync(path.join(scratch, 'extension with spaces-'));
    const environment = runtime(pathToFileURL(directory).href);
    const missing = loadEndpointConfig(environment);
    assert.equal(missing.endpoint, DEFAULT_MCP_ENDPOINT);
    assert.match(missing.source, /connection\.json not found/);
    const file = path.join(directory, 'connection.json');
    fs.writeFileSync(file, '\uFEFF{"endpoint":"ws://127.0.0.1:8082"}');
    const loaded = loadEndpointConfig(environment);
    assert.equal(loaded.endpoint, 'ws://127.0.0.1:8082');
    assert.equal(loaded.source, file);
    fs.writeFileSync(file, '{"endpoint":"ws://localhost:9090"}');
    assert.equal(loaded.endpoint, 'ws://127.0.0.1:8082');
    assert.equal(loadEndpointConfig(environment).endpoint, 'ws://localhost:9090');
    fs.unlinkSync(file);
    assert.equal(loadEndpointConfig(environment).endpoint, DEFAULT_MCP_ENDPOINT);
});

test('CEP native and file URL paths resolve in the installed root on both platforms', () => {
    const cases = [
        ['/Users/keda/My Panel', path.posix, '/Users/keda/My Panel/connection.json'],
        ['file:///Users/keda/My%20Panel', path.posix, '/Users/keda/My Panel/connection.json'],
        ['file:///Users/keda/%E5%9B%BE%20%23100%25', path.posix, '/Users/keda/图 #100%/connection.json'],
        ['C:\\Users\\Keda\\My Panel', path.win32, 'C:\\Users\\Keda\\My Panel\\connection.json'],
        ['file:///C:/Users/Keda/My%20Panel', path.win32, 'C:\\Users\\Keda\\My Panel\\connection.json'],
    ];
    for (const [directory, pathModule, expected] of cases) {
        const environment = runtime(directory, { path: pathModule, fs: { readFileSync: (file, encoding) => {
            assert.equal(file, expected);
            assert.equal(encoding, 'utf8');
            return '{"endpoint":"ws://127.0.0.1:8082"}';
        } } });
        assert.equal(loadEndpointConfig(environment).endpoint, 'ws://127.0.0.1:8082');
        // Older/mixed CEP contexts also expose require on window.
        environment.require = environment.cep_node.require;
        delete environment.cep_node;
        assert.equal(loadEndpointConfig(environment).endpoint, 'ws://127.0.0.1:8082');
    }
});

test('missing CEP capabilities, bad paths, and non-ENOENT reads fail visibly', () => {
    const cases = [
        { __adobe_cep__: {} },
        runtime('relative/extension'),
        runtime('/extension', { fs: { readFileSync: () => { throw Object.assign(new Error('permission denied'), { code: 'EACCES' }); } } }),
        runtime('/extension', { fs: { readFileSync: () => '{broken' } }),
    ];
    for (const environment of cases) {
        const loaded = loadEndpointConfig(environment);
        assert.equal(loaded.endpoint, null);
        assert.match(loaded.error, /reload the panel/);
        assert.match(loaded.error, /connection\.json/);
    }
});

test('valid WebSocket URLs include custom host/port and IPv6', () => {
    for (const endpoint of ['ws://127.0.0.1:8082', 'ws://localhost:65535', 'ws://[::1]:8082', 'wss://example.test/bridge']) {
        assert.equal(parseEndpointConfig(JSON.stringify({ endpoint: ` ${endpoint} ` })), endpoint);
    }
});

test('invalid configurations never silently fall back to port 8081', () => {
    const bad = ['', '{}', 'null', '[]', '{"endpoint":8082}', '{"endpont":"ws://localhost:8082"}',
        '{"endpoint":"ws://localhost:8082","port":9090}'];
    const urls = ['', 'http://localhost:8082', 'localhost:8082', '/bridge', 'ws://', 'ws:///localhost:8082',
        'ws://localhost:0', 'ws://localhost:65536', 'ws://localhost:port',
        'ws://user:secret@localhost:8082', 'ws://localhost:8082#', 'ws://local host:8082',
        'ws://localhost:\n8082', 'ws://localhost\\path'];
    for (const text of [...bad, ...urls.map(endpoint => JSON.stringify({ endpoint }))]) {
        assert.throws(() => parseEndpointConfig(text), undefined, text);
    }
});

function harness(endpointConfig = config(DEFAULT_MCP_ENDPOINT)) {
    const sockets = [], endpoints = [], logs = [], messages = [], timeouts = new Map(), intervals = new Map();
    let id = 0, connected = 0;
    const createSocket = endpoint => {
        endpoints.push(endpoint);
        const socket = { readyState: 0, onopen: null, onclose: null, onmessage: null, onerror: null,
            sent: [], closeCalls: 0,
            send(data) { this.sent.push(data); },
            close() { this.closeCalls++; this.readyState = 2; },
            open() { this.readyState = 1; this.onopen({}); },
            closed(code) { this.readyState = 3; this.onclose({ code }); },
        };
        sockets.push(socket);
        return socket;
    };
    const options = {
        endpointConfig, createSocket,
        clock: {
            setTimeout: (fn, delay) => { assert.equal(delay, 3000); timeouts.set(++id, fn); return id; },
            clearTimeout: id => timeouts.delete(id),
            setInterval: (fn, delay) => { assert.equal(delay, 5000); intervals.set(++id, fn); return id; },
            clearInterval: id => intervals.delete(id),
        },
        log: (message, type) => logs.push({ message, type }),
        onMessage: data => messages.push(data), onConnected: () => connected++, heartbeat: () => 'heartbeat',
    };
    const controller = new ConnectionController(options);
    return { controller, options, sockets, endpoints, logs, messages, timeouts, intervals, connected: () => connected };
}

test('default and configured endpoints reach the socket factory and diagnostics', () => {
    for (const endpoint of [DEFAULT_MCP_ENDPOINT, 'ws://127.0.0.1:8082']) {
        const h = harness(config(endpoint));
        h.controller.connect();
        assert.deepEqual(h.endpoints, [endpoint]);
        assert.equal(h.logs[0].message, `Connecting to ${endpoint}…`);
        h.sockets[0].open();
        assert.equal(h.controller.getSnapshot().status, 'connected');
        assert.equal(h.connected(), 1);
        assert.equal(h.controller.send('completion'), 'submitted');
        [...h.intervals.values()][0]();
        assert.deepEqual(h.sockets[0].sent, ['completion', 'heartbeat']);
        h.controller.dispose();
        assert.equal(h.intervals.size, 0);
    }
});

test('configuration errors stop before socket creation and preserve useful status text', () => {
    const h = harness({ endpoint: null, source: '/panel/connection.json', error: 'Invalid JSON. Reload the panel.' });
    h.controller.connect();
    h.controller.connect();
    const snapshot = h.controller.getSnapshot();
    assert.equal(snapshot.failure, 'configuration');
    assert.equal(snapshot.wanted, false);
    assert.equal(snapshot.attempt, 0);
    assert.equal(h.endpoints.length, 0);
    assert.equal(h.timeouts.size, 0);
    assert.equal(selectConnectionControl(snapshot).statusLabel, 'Configuration error');
    assert.match(selectConnectionControl(snapshot).statusText, /Invalid JSON/);
});

test('retries reuse the configured endpoint; stale callbacks cannot create duplicate sockets', () => {
    const h = harness(config('ws://127.0.0.1:8082'));
    h.controller.connect();
    const first = h.sockets[0];
    first.open();
    const oldHeartbeat = [...h.intervals.values()][0];
    first.closed(1006);
    assert.equal(h.controller.getSnapshot().status, 'retrying');
    assert.equal(h.intervals.size, 0);
    const retry = [...h.timeouts.values()][0];
    retry(); retry();
    assert.deepEqual(h.endpoints, ['ws://127.0.0.1:8082', 'ws://127.0.0.1:8082']);
    h.sockets[1].open();
    first.onmessage({ data: 'stale' });
    first.onclose({ code: 4001 });
    oldHeartbeat();
    assert.deepEqual(h.messages, []);
    assert.equal(h.controller.getSnapshot().status, 'connected');
    assert.deepEqual(first.sent, []);
});

test('4001 conflict pauses retries and keeps the existing occupied-server diagnostic', () => {
    const h = harness(config('ws://localhost:8082'));
    h.controller.connect();
    h.sockets[0].open();
    h.sockets[0].closed(4001);
    const control = selectConnectionControl(h.controller.getSnapshot());
    assert.equal(control.statusLabel, 'Server occupied');
    assert.equal(control.label, 'Retry');
    assert.match(control.statusText, /Another panel connection/);
    assert.equal(h.timeouts.size, 0);
    assert.equal(h.intervals.size, 0);
    h.controller.connect();
    assert.deepEqual(h.endpoints, ['ws://localhost:8082', 'ws://localhost:8082']);
});

test('manual disconnect cancels pending retries and waits for active socket closure', () => {
    const h = harness();
    h.controller.connect();
    h.sockets[0].closed(1006);
    const retry = [...h.timeouts.values()][0];
    h.controller.disconnect();
    retry();
    assert.equal(h.sockets.length, 1);
    assert.equal(h.timeouts.size, 0);
    h.controller.connect();
    const second = h.sockets[1];
    h.controller.disconnect();
    h.controller.connect();
    assert.equal(h.sockets.length, 2);
    assert.equal(h.controller.getSnapshot().status, 'disconnecting');
    assert.equal(h.controller.send('completion'), 'not_submitted');
    second.closed(1000);
    assert.equal(h.controller.getSnapshot().status, 'disconnected');
});

test('socket construction failures retain their original separate diagnostic', () => {
    const h = harness(config('ws://127.0.0.1:8082'));
    h.options.createSocket = () => { throw new Error('test constructor failure'); };
    h.controller.connect();
    assert.equal(h.controller.getSnapshot().failure, 'creation');
    assert.match(selectConnectionControl(h.controller.getSnapshot()).statusText, /test constructor failure/);
    assert.equal(h.timeouts.size, 0);
});

test('dispose cancels retries and ignores delayed callbacks', () => {
    const h = harness();
    h.controller.connect();
    h.sockets[0].closed(1006);
    const retry = [...h.timeouts.values()][0];
    h.controller.dispose();
    retry();
    h.controller.connect();
    assert.equal(h.sockets.length, 1);
    assert.equal(h.timeouts.size, 0);
});
