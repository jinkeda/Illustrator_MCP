import { useState, useEffect, useRef, useCallback } from 'react';

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

export type ConnectionStatus = 'connected' | 'disconnected' | 'connecting' | 'error';

// Response types for streaming
interface ProgressResponse {
    id: number;
    type: 'progress';
    index: number;
    total?: number;
    message?: string;
}

interface CompleteResponse {
    id: number;
    type: 'complete';
    command: string;
    result?: any;
    error?: string;
    duration: number;
}

export function useMCP() {
    const [status, setStatus] = useState<ConnectionStatus>('disconnected');
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const ws = useRef<WebSocket | null>(null);
    const reconnectTimeout = useRef<number | null>(null);
    const csInterface = useRef<CSInterface | null>(null);

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
        if (csInterface.current) {
            csInterface.current.evalScript(script);
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


    const connect = useCallback(() => {
        if (ws.current?.readyState === WebSocket.OPEN) return;

        setStatus('connecting');
        addLog('Connecting to 127.0.0.1:8081...', 'info');

        try {
            const socket = new WebSocket('ws://127.0.0.1:8081');
            ws.current = socket;

            socket.onopen = () => {
                setStatus('connected');
                addLog('Connected to MCP Server', 'success');
                if (reconnectTimeout.current) {
                    window.clearTimeout(reconnectTimeout.current);
                    reconnectTimeout.current = null;
                }
            };

            socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    // Handle script execution requests
                    if (data.script && data.id) {
                        const cmdType = data.command?.type || 'script';
                        const isStreaming = data.streaming === true;

                        addLog(`▶ ${cmdType}${isStreaming ? ' (streaming)' : ''}`, 'info');

                        // Measure execution time
                        const startTime = performance.now();

                        // Execute via host script
                        const script = `mcp_handle_request(${JSON.stringify(data)})`;

                        if (csInterface.current) {
                            // For streaming requests, we need special handling
                            if (isStreaming) {
                                // Execute and periodically check for results
                                // The host script should return progress updates
                                csInterface.current.evalScript(script, (result: string) => {
                                    const duration = Math.round(performance.now() - startTime);

                                    // Parse result
                                    let parsedResult: any;
                                    try {
                                        parsedResult = JSON.parse(result);
                                    } catch (e) {
                                        parsedResult = { result };
                                    }

                                    // Send progress updates if available
                                    if (parsedResult.progress && Array.isArray(parsedResult.progress)) {
                                        for (const update of parsedResult.progress) {
                                            const progressResponse: ProgressResponse = {
                                                id: data.id,
                                                type: 'progress',
                                                index: update.index || 0,
                                                total: update.total,
                                                message: update.message
                                            };
                                            if (socket.readyState === WebSocket.OPEN) {
                                                socket.send(JSON.stringify(progressResponse));
                                            }
                                        }
                                    }

                                    // Send final complete response
                                    const completeResponse: CompleteResponse = {
                                        id: data.id,
                                        type: 'complete',
                                        command: cmdType,
                                        result: parsedResult.result ?? parsedResult,
                                        error: parsedResult.error,
                                        duration
                                    };

                                    if (socket.readyState === WebSocket.OPEN) {
                                        socket.send(JSON.stringify(completeResponse));
                                        addLog(`✓ ${cmdType} (${duration}ms)`, 'success');
                                    }
                                });
                            } else {
                                // Non-streaming: single response
                                csInterface.current.evalScript(script, (result: string) => {
                                    const duration = Math.round(performance.now() - startTime);

                                    // Parse result
                                    let parsedResult: any;
                                    try {
                                        parsedResult = JSON.parse(result);
                                    } catch (e) {
                                        parsedResult = { result };
                                    }

                                    const response: CompleteResponse = {
                                        id: data.id,
                                        type: 'complete',
                                        command: cmdType,
                                        result: parsedResult.result ?? parsedResult,
                                        error: parsedResult.error,
                                        duration
                                    };

                                    if (socket.readyState === WebSocket.OPEN) {
                                        socket.send(JSON.stringify(response));
                                        addLog(`✓ ${cmdType} (${duration}ms)`, 'success');
                                    }
                                });
                            }
                        } else {
                            addLog(`Simulated execution: ${data.script}`, 'debug');
                            // Mock response
                            setTimeout(() => {
                                socket.send(JSON.stringify({
                                    id: data.id,
                                    type: 'complete',
                                    result: "Mock Success",
                                    duration: 500
                                }));
                            }, 500);
                        }
                    }

                } catch (e) {
                    addLog(`Error parsing message: ${e}`, 'error');
                }
            };

            socket.onclose = (event) => {
                setStatus('disconnected');
                ws.current = null;
                if (event.code !== 1000) { // Normal closure
                    addLog(`Disconnected (code: ${event.code}). Retrying...`, 'warning');
                    reconnectTimeout.current = window.setTimeout(connect, 3000);
                } else {
                    addLog('Disconnected', 'info');
                }
            };

            socket.onerror = (error) => {
                console.error('WebSocket error:', error);
                setStatus('error');
            };

        } catch (e) {
            addLog(`Connection failed: ${e}`, 'error');
            setStatus('error');
        }
    }, [addLog]);

    const disconnect = useCallback(() => {
        if (reconnectTimeout.current) {
            window.clearTimeout(reconnectTimeout.current);
            reconnectTimeout.current = null;
        }
        if (ws.current) {
            ws.current.close(1000);
            ws.current = null;
        }
    }, []);

    // Auto-connect on mount
    useEffect(() => {
        connect();
        return () => disconnect();
    }, [connect, disconnect]);

    return {
        status,
        logs,
        connect,
        disconnect,
        mcpDispatch, // Expose for UI actions
        executeScript // Expose for debugging
    };
}
