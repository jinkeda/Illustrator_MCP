import { useState, useEffect, useRef, useCallback } from 'react';
import { ConnectionController, ConnectionSnapshot, selectConnectionControl } from '../connection/ConnectionController';
import { loadEndpointConfig } from '../connection/EndpointConfig';

// ExtendScript types
interface CSInterface {
    evalScript(script: string, callback?: (result: string) => void): void;
}

declare global {
    interface Window {
        __adobe_cep__: any;
        CSInterface: new () => CSInterface;
    }
}

// Log entry type
export interface LogEntry {
    id: string;
    timestamp: string;
    message: string;
    type: 'info' | 'success' | 'error' | 'warning' | 'debug';
}

export type ConnectionStatus = ConnectionSnapshot['status'];

// Response types for streaming
interface ProgressResponse {
    id: number;
    type: 'progress';
    index: number;
    total?: number;
    message?: string;
    requestToken?: string;
}

interface CompleteResponse {
    id: number;
    type: 'complete';
    command: string;
    result?: any;
    error?: string;
    payloadError?: string;
    duration: number;
    requestToken?: string;
    jobId?: string;
    connectionGeneration?: number;
    payloadFrames?: any[]; // Retained locally for reconnect replay, never one giant frame.
}

export async function collectPayload(host: CSInterface, request: any, descriptor: any): Promise<any[]> {
    if (!descriptor || descriptor.version !== 1 || descriptor.pageBytes !== 12288 ||
        !Number.isInteger(descriptor.byteLength) || descriptor.byteLength < 0 || descriptor.byteLength > 32 * 1024 * 1024) {
        throw new Error('invalid payload descriptor');
    }
    const owner = {payloadId: descriptor.payloadId, sessionId: request.transport.sessionId,
        jobId: request.jobId, requestToken: request.requestToken};
    const evaluate = (script: string): Promise<any> => new Promise((resolve, reject) => {
        let settled = false;
        const timer = window.setTimeout(() => {
            if (!settled) { settled = true; reject(new Error('payload read timed out')); }
        }, 15000);
        host.evalScript(script, raw => {
            if (settled) return;
            settled = true;
            window.clearTimeout(timer);
            try { resolve(JSON.parse(raw)); } catch (error) { reject(error); }
        });
    });
    const frames: any[] = [{type:'payload_descriptor', id:request.id,
        requestToken:request.requestToken, descriptor}];
    try {
        for (let offset = 0; offset < descriptor.byteLength; offset += descriptor.pageBytes) {
            let page: any;
            for (let attempt = 0; attempt < 2; attempt++) {
                try {
                    page = await evaluate(`mcp_payload_read(${JSON.stringify({...owner, offset})})`);
                    if (page.payloadError) throw Object.assign(new Error(page.payloadError), {payloadError:page.payloadError});
                    if (page.offset !== offset || page.payloadId !== descriptor.payloadId ||
                        typeof page.data !== 'string' || page.data.length > 16384) throw new Error('invalid payload page');
                    break;
                } catch (error) { if (attempt === 1) throw error; }
            }
            frames.push({...page, id:request.id, requestToken:request.requestToken, type:'payload_chunk'});
        }
        return frames;
    } finally {
        // Only this immutable snapshot is released. A failed read never repeats
        // the original script. TTL handles a lost release callback or panel exit.
        try { await evaluate(`mcp_payload_release(${JSON.stringify(owner)})`); } catch (_) { /* bounded host TTL */ }
    }
}

export function useMCP() {
    const [endpointConfig] = useState(() => loadEndpointConfig(window));
    const [connection, setConnection] = useState<ConnectionSnapshot>({
        status:'disconnected', wanted:false, failure:null, attempt:0,
    });
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const controller = useRef<ConnectionController | null>(null);
    const csInterface = useRef<CSInterface | null>(null);

    const isExecuting = useRef(false);
    const activeRequestId = useRef<number | null>(null);
    const connectedAt = useRef(0);
    // Keep completions until the server acknowledges them. A socket closing
    // does not stop evalScript, and its callback may arrive on a later socket.
    const completions = useRef(new Map<string, CompleteResponse>());
    const submitCompletion = useCallback((response: CompleteResponse) => {
        const transport = controller.current;
        if (!transport) return;
        const attempt = transport.getSnapshot().attempt;
        const {payloadFrames = [], ...complete} = response;
        // One retained batch, always replayed from its beginning. A send result
        // only reports synchronous submission; only the matching ACK clears it.
        try {
            for (const frame of [...payloadFrames, complete]) {
                const serialized = JSON.stringify(frame);
                if (controller.current !== transport || transport.getSnapshot().attempt !== attempt ||
                    transport.send(serialized) !== 'submitted') break;
            }
        } catch (_) { /* Serialization failure leaves the original batch retained. */ }
    }, []);
    const sendCompletion = useCallback((request: any, response: CompleteResponse) => {
        response.requestToken = request.requestToken;
        response.jobId = request.jobId;
        response.connectionGeneration = request.connectionGeneration;
        if (request.requestToken) completions.current.set(request.requestToken, response);
        submitCompletion(response);
    }, [submitCompletion]);

    const heartbeat = useCallback(() => JSON.stringify({type:'heartbeat',
        busy:isExecuting.current || completions.current.size > 0,
        activeRequestId:activeRequestId.current, uptimeMs:Date.now() - connectedAt.current,
        capabilities:['payload-v1']}), []);

    // Initialize CSInterface
    useEffect(() => {
        if (window.__adobe_cep__) {
            csInterface.current = new window.CSInterface();
        }
    }, []);

    const addLog = useCallback((message: string, type: LogEntry['type'] = 'info') => {
        const now = new Date();
        const timeString = now.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const id = Math.random().toString(36).substring(7);

        setLogs(prev => {
            const newLogs = [...prev, { id, timestamp: timeString, message, type }];
            return newLogs.slice(-100); // Keep last 100
        });
    }, []);

    const executeScript = useCallback((script: string) => {
        if (isExecuting.current || completions.current.size) return;
        if (csInterface.current) {
            isExecuting.current = true;
            csInterface.current.evalScript(script, () => { isExecuting.current = false; });
        } else {
            console.log('Mock execution:', script);
        }
    }, []);

    // Safe dispatcher
    const mcpDispatch = useCallback((command: string, payload: any) => {
        const payloadStr = JSON.stringify(payload)
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/"/g, '\\"');

        const script = `mcp_dispatch("${command}", JSON.parse("${payloadStr}"))`;
        executeScript(script);
    }, [executeScript]);


    const onMessage = useCallback((serialized: string) => {
        try {
            const data = JSON.parse(serialized);
            if (data.type === 'completion_ack' && data.requestToken) {
                completions.current.delete(data.requestToken);
                controller.current?.send(heartbeat());
                return;
            }

            // Handle script execution requests
            if (data.script && data.id) {
                // Busy guard: reject if already executing
                if (isExecuting.current || completions.current.size) {
                    if (controller.current) {
                        controller.current?.send(JSON.stringify({
                            id: data.id,
                            requestToken: data.requestToken,
                            type: 'complete',
                            error: `BUSY: Script ${activeRequestId.current} still executing`,
                        }));
                        addLog(`⊘ Rejected ${data.id} (busy)`, 'warning');
                    }
                    return;
                }

                isExecuting.current = true;
                activeRequestId.current = data.id;

                const cmdType = data.command?.type || 'script';
                const isStreaming = data.streaming === true;

                addLog(`▶ ${cmdType}${isStreaming ? ' (streaming)' : ''}`, 'info');

                // Measure execution time
                const startTime = performance.now();

                // Execute via host script
                const script = `mcp_handle_request(${JSON.stringify(data)})`;

                if (csInterface.current) {
                    csInterface.current.evalScript(script, (result: string) => {
                        const duration = Math.round(performance.now() - startTime);
                        let parsedResult: any;
                        try { parsedResult = JSON.parse(result); }
                        catch (_) { parsedResult = {result}; }
                        const finish = (response: CompleteResponse) => {
                            isExecuting.current = false;
                            activeRequestId.current = null;
                            sendCompletion(data, response);
                            addLog(`Completed ${cmdType} (${duration}ms)`, response.error ? 'error' : 'success');
                        };
                        if (data.transport) {
                            if (!parsedResult.payloadDescriptor) {
                                finish({id:data.id, type:'complete', command:cmdType, duration,
                                    payloadError:parsedResult.payloadError,
                                    error: `Payload descriptor unavailable: ${parsedResult.payloadError || 'host upgrade required'}`});
                                return;
                            }
                            collectPayload(csInterface.current!, data, parsedResult.payloadDescriptor).then(frames => {
                                finish({id:data.id, type:'complete', command:cmdType, duration, payloadFrames:frames});
                            }).catch(error => {
                                finish({id:data.id, type:'complete', command:cmdType, duration,
                                    error:String(error), payloadError:error.payloadError, payloadFrames:[{type:'payload_descriptor', id:data.id,
                                        requestToken:data.requestToken, descriptor:parsedResult.payloadDescriptor}]});
                            });
                            return;
                        }
                        if (isStreaming && Array.isArray(parsedResult.progress)) {
                            parsedResult.progress.forEach((update: any) => {
                                const progress: ProgressResponse = {id:data.id, requestToken:data.requestToken,
                                    type:'progress', index:update.index || 0, total:update.total, message:update.message};
                                controller.current?.send(JSON.stringify(progress));
                            });
                        }
                        finish({id:data.id, type:'complete', command:cmdType, duration,
                            result:parsedResult.result ?? parsedResult, error:parsedResult.error});
                    });
                } else {
                    addLog(`Simulated execution: ${data.script}`, 'debug');
                    // Follow the same completion/ACK lifecycle in browser previews.
                    setTimeout(() => {
                        isExecuting.current = false;
                        activeRequestId.current = null;
                        sendCompletion(data, {id:data.id, type:'complete', command:cmdType,
                            result:'Mock Success', duration:500});
                    }, 500);
                }
            }

        } catch (e) {
            addLog(`Error parsing message: ${e}`, 'error');
        }
    }, [addLog, sendCompletion, heartbeat]);

    const connect = useCallback(() => controller.current?.connect(), []);
    const disconnect = useCallback(() => {
        controller.current?.disconnect();
        addLog('Disconnected transport. Running Illustrator requests continue.', 'info');
    }, [addLog]);

    useEffect(() => {
        const transport = new ConnectionController({
            endpointConfig,
            createSocket: endpoint => new WebSocket(endpoint),
            clock: {
                setTimeout: (fn, ms) => window.setTimeout(fn, ms),
                clearTimeout: id => window.clearTimeout(id),
                setInterval: (fn, ms) => window.setInterval(fn, ms),
                clearInterval: id => window.clearInterval(id),
            },
            log: addLog,
            onMessage,
            heartbeat,
            onConnected: () => {
                connectedAt.current = Date.now();
                transport.send(heartbeat());
                completions.current.forEach(submitCompletion);
            },
        });
        controller.current = transport;
        const unsubscribe = transport.subscribe(setConnection);
        addLog(`Endpoint configuration: ${endpointConfig.source}`, 'info');
        transport.connect();
        return () => {
            unsubscribe();
            transport.dispose();
            if (controller.current === transport) controller.current = null;
        };
    }, [addLog, onMessage, heartbeat, submitCompletion, endpointConfig]);

    return {
        status: connection.status,
        endpointConfig,
        connectionControl: selectConnectionControl(connection),
        logs,
        connect,
        disconnect,
        mcpDispatch, // Expose for UI actions
        executeScript // Expose for debugging
    };
}
