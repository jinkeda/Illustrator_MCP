export const DEFAULT_MCP_ENDPOINT = 'ws://127.0.0.1:8081';
export const ENDPOINT_CONFIG_FILE = 'connection.json';

export type EndpointConfig =
    | { endpoint: string; source: string; error?: never }
    | { endpoint: null; source: string; error: string };

// CEP supplies Node at runtime. Do not import fs/path into the browser bundle.
interface CEPRuntime {
    __adobe_cep__?: { getSystemPath: (type: string) => string };
    cep_node?: { require: (name: string) => any };
    require?: (name: string) => any;
}

export function parseEndpointConfig(text: string): string {
    const config: unknown = JSON.parse(text.replace(/^\uFEFF/, ''));
    if (!config || typeof config !== 'object' || Array.isArray(config) ||
        Object.keys(config).length !== 1 || !('endpoint' in config) ||
        typeof config.endpoint !== 'string') {
        throw new Error('Expected a JSON object with one "endpoint" string.');
    }
    const endpoint = config.endpoint.trim();
    if (!/^wss?:\/\/[^/?#]/i.test(endpoint) || /[\s\\#]/.test(endpoint)) {
        throw new Error('endpoint must be an absolute ws:// or wss:// URL without whitespace or a fragment.');
    }
    const url = new URL(endpoint);
    if (!url.hostname || url.username || url.password || url.port === '0') {
        throw new Error('endpoint must have a host, a valid port (1–65535), and no credentials.');
    }
    return endpoint;
}

/** Read once per panel load so reconnects keep the same server and completion ledger. */
export function loadEndpointConfig(runtime: CEPRuntime): EndpointConfig {
    if (!runtime.__adobe_cep__) {
        return { endpoint: DEFAULT_MCP_ENDPOINT, source: 'default (browser preview)' };
    }
    let source = ENDPOINT_CONFIG_FILE;
    try {
        const nodeRequire = runtime.cep_node?.require || runtime.require;
        if (typeof nodeRequire !== 'function') throw new Error('CEP Node.js is unavailable.');
        const fs = nodeRequire('fs');
        const path = nodeRequire('path');
        // The bundled CSInterface shim returns the raw CEP path, unlike Adobe's
        // full CSInterface. Handle file:///C:/... and file:///Users/... as well
        // as native paths, without relying on Illustrator's working directory.
        let directory = runtime.__adobe_cep__.getSystemPath('extension');
        if (directory.startsWith('file://')) {
            directory = decodeURIComponent(directory)
                .replace(/^file:\/\/\/(?=[A-Za-z]:[\\/])/, '')
                .replace(/^file:\/\//, '');
        }
        if (!path.isAbsolute(directory)) throw new Error('CEP extension path is not absolute.');
        source = path.join(directory, ENDPOINT_CONFIG_FILE);
        let contents: string;
        try { contents = fs.readFileSync(source, 'utf8'); }
        catch (error) {
            if ((error as { code?: string }).code === 'ENOENT') {
                return { endpoint: DEFAULT_MCP_ENDPOINT, source: `default (${source} not found)` };
            }
            throw error;
        }
        return { endpoint: parseEndpointConfig(contents), source };
    } catch (error) {
        return { endpoint: null, source, error: `${source}: ${String(error)} Fix the configuration and reload the panel.` };
    }
}
