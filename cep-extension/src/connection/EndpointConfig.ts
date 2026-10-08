export const DEFAULT_MCP_ENDPOINT = 'ws://127.0.0.1:8081';
export const ENDPOINT_CONFIG_FILE = 'connection.json';

export type EndpointConfig =
    | { endpoint: string; source: string; error?: never }
    | { endpoint: null; source: string; error: string };

interface CEPRuntime {
    __adobe_cep__?: { getSystemPath: (type: string) => string };
    cep_node?: { require: (name: string) => any };
    require?: (name: string) => any;
}

/** Deliberately narrower than URL(): both ends support IPv4 loopback only. */
export function parseEndpointConfig(text: string): string {
    const config: unknown = JSON.parse(text.replace(/^\uFEFF/, ''));
    if (!config || typeof config !== 'object' || Array.isArray(config) ||
        Object.keys(config).length !== 1 || !('endpoint' in config) ||
        typeof config.endpoint !== 'string') {
        throw new Error('Expected a JSON object with one "endpoint" string.');
    }
    const match = /^ws:\/\/(127\.0\.0\.1|localhost):([0-9]{1,5})\/?$/i.exec(config.endpoint.trim());
    if (!match || Number(match[2]) < 1024 || Number(match[2]) > 65535) {
        throw new Error('Use ws://127.0.0.1:PORT or ws://localhost:PORT, with an explicit port from 1024 to 65535 and no path, query, credentials or fragment.');
    }
    return `ws://127.0.0.1:${Number(match[2])}`;
}

/** Configuration and completion destination remain fixed for this panel lifetime. */
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
        let directory = runtime.__adobe_cep__.getSystemPath('extension');
        if (/^file:/i.test(directory)) {
            const url = new URL(directory);
            if (url.hostname && url.hostname !== 'localhost') throw new Error('CEP extension path must be local.');
            directory = decodeURIComponent(url.pathname).replace(/^\/(?=[A-Za-z]:[\\/])/, '');
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
        return { endpoint: null, source, error: `${source}: ${String(error)} Fix the configuration and reload the panel after pending work is resolved.` };
    }
}
