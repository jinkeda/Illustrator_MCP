import type { EndpointConfig } from './EndpointConfig';

export interface ConnectionSnapshot {
    status: 'disconnected' | 'connecting' | 'connected' | 'disconnecting' | 'retrying' | 'error';
    wanted: boolean;
    failure: 'conflict' | 'creation' | 'configuration' | null;
    detail?: string;
    attempt: number;
}

export function selectConnectionControl(state: ConnectionSnapshot) {
    const action: 'connect' | 'disconnect' = state.wanted ? 'disconnect' : 'connect';
    let statusText = 'Disconnected. Automatic reconnect is paused.';
    if (state.status === 'connected') statusText = 'Connected';
    else if (state.status === 'connecting') statusText = 'Connecting…';
    else if (state.status === 'disconnecting') statusText = 'Disconnecting…';
    else if (state.failure === 'conflict') statusText = 'Another panel connection occupies the server. Release it before retrying.';
    else if (state.failure === 'creation') statusText = `Could not create connection: ${state.detail}`;
    else if (state.failure === 'configuration') statusText = `Invalid endpoint configuration: ${state.detail}`;
    else if (state.status === 'retrying') statusText = 'Connection lost. Retrying in 3 seconds.';
    const statusLabel = state.failure === 'conflict' ? 'Server occupied'
        : state.failure === 'creation' ? 'Connection failed'
        : state.failure === 'configuration' ? 'Configuration error'
        : state.status === 'retrying' ? 'Retrying…'
        : state.status === 'disconnected' ? 'Offline' : statusText;
    return {action, label: state.wanted ? 'Disconnect' : state.failure ? 'Retry' : 'Connect',
        enabled: state.status !== 'disconnecting', statusText, statusLabel};
}

// Use the DOM handler contracts so native WebSocket is assignable under strict
// function variance. Tests still inject only this small structural surface.
type Socket = Pick<WebSocket,
    'readyState' | 'onopen' | 'onmessage' | 'onerror' | 'onclose' | 'send' | 'close'>;
interface Options {
    endpointConfig: EndpointConfig;
    createSocket: (endpoint: string) => Socket;
    clock: {
        setTimeout: (callback: () => void, delay: number) => number;
        clearTimeout: (id: number) => void;
        setInterval: (callback: () => void, delay: number) => number;
        clearInterval: (id: number) => void;
    };
    onMessage: (data: string) => void;
    onConnected: () => void;
    heartbeat: () => string;
    log: (message: string, type: 'info' | 'success' | 'warning' | 'error') => void;
}

/** Owns transport only. Host execution and the completion ledger outlive sockets. */
export class ConnectionController {
    private state: ConnectionSnapshot = {status:'disconnected', wanted:false, failure:null, attempt:0};
    private socket: Socket | null = null;
    private admitted = false;
    private disposed = false;
    private retryTimer: number | null = null;
    private heartbeatTimer: number | null = null;
    private retryTicket = 0;
    private heartbeatTicket = 0;
    private listeners = new Set<(state: ConnectionSnapshot) => void>();

    constructor(private readonly options: Options) {}

    getSnapshot = (): ConnectionSnapshot => ({...this.state});
    subscribe = (listener: (state: ConnectionSnapshot) => void) => {
        if (!this.disposed) this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    };
    private publish(update: Partial<ConnectionSnapshot>) {
        this.state = {...this.state, ...update};
        if (!this.disposed) this.listeners.forEach(listener => listener(this.getSnapshot()));
    }
    private clearRetry() {
        this.retryTicket++;
        if (this.retryTimer !== null) this.options.clock.clearTimeout(this.retryTimer);
        this.retryTimer = null;
    }
    private clearHeartbeat() {
        this.heartbeatTicket++;
        if (this.heartbeatTimer !== null) this.options.clock.clearInterval(this.heartbeatTimer);
        this.heartbeatTimer = null;
    }
    private requestClose(socket: Socket) {
        try { socket.close(1000); }
        catch (error) {
            // Never relinquish ownership based on an unconfirmed close.
            if (!this.disposed) this.options.log(`Could not request socket closure: ${error}`, 'error');
        }
    }

    connect = () => {
        this.clearRetry();
        if (this.disposed || this.socket) return;
        const { endpoint, error } = this.options.endpointConfig;
        if (endpoint === null) {
            this.publish({wanted:false, status:'error', failure:'configuration', detail:error});
            this.options.log(selectConnectionControl(this.state).statusText, 'error');
            return;
        }
        this.publish({wanted:true, status:'connecting', failure:null, detail:undefined, attempt:this.state.attempt+1});
        this.options.log(`Connecting to ${endpoint}…`, 'info');
        let socket: Socket;
        try { socket = this.options.createSocket(endpoint); }
        catch (error) {
            this.publish({wanted:false, status:'error', failure:'creation', detail:String(error)});
            this.options.log(`Could not create connection: ${error}`, 'error');
            return;
        }
        this.socket = socket;
        const attempt = this.state.attempt;
        const owns = () => !this.disposed && this.socket === socket && this.state.attempt === attempt;
        const accepts = () => owns() && this.state.wanted && this.admitted && socket.readyState === 1;
        socket.onopen = () => {
            if (!owns() || !this.state.wanted) { this.requestClose(socket); return; }
            if (this.admitted) return;
            this.admitted = true;
            this.clearHeartbeat();
            this.publish({status:'connected'});
            this.options.log('Connected to MCP Server', 'success');
            // Hook callback sends the initial busy heartbeat and replays completions once.
            this.options.onConnected();
            if (!accepts()) return;
            const ticket = this.heartbeatTicket;
            this.heartbeatTimer = this.options.clock.setInterval(() => {
                if (accepts() && ticket === this.heartbeatTicket) this.send(this.options.heartbeat());
            }, 5000);
        };
        socket.onmessage = event => {
            if (accepts() && typeof event.data === 'string') this.options.onMessage(event.data);
        };
        socket.onerror = () => {
            if (owns() && this.state.wanted) this.options.log('WebSocket transport error; waiting for closure to retry.', 'warning');
        };
        socket.onclose = event => {
            if (!owns()) return;
            this.socket = null;
            this.admitted = false;
            this.clearHeartbeat();
            if (!this.state.wanted) { this.publish({status:'disconnected'}); return; }
            if (event.code === 4001) {
                this.clearRetry();
                this.publish({wanted:false, status:'error', failure:'conflict'});
                this.options.log(selectConnectionControl(this.state).statusText, 'warning');
                return;
            }
            this.clearRetry();
            this.publish({status:'retrying'});
            this.options.log(`Disconnected (code: ${event.code}). Retrying in 3 seconds.`, 'warning');
            const ticket = this.retryTicket;
            this.retryTimer = this.options.clock.setTimeout(() => {
                if (this.disposed || !this.state.wanted || ticket !== this.retryTicket || attempt !== this.state.attempt) return;
                this.clearRetry(); // Consume the ticket, even if the callback is delivered twice.
                this.connect();
            }, 3000);
        };
    };

    disconnect = () => {
        if (this.disposed) return;
        this.state = {...this.state, wanted:false};
        this.clearRetry();
        this.clearHeartbeat();
        this.admitted = false;
        this.publish({status:this.socket ? 'disconnecting' : 'disconnected', failure:null, detail:undefined});
        if (this.socket && this.socket.readyState !== 2) this.requestClose(this.socket);
    };

    send = (serializedFrame: string): 'submitted' | 'not_submitted' => {
        if (this.disposed || !this.state.wanted || !this.admitted || this.socket?.readyState !== 1) return 'not_submitted';
        try { this.socket.send(serializedFrame); return 'submitted'; }
        catch (error) { this.options.log(`Socket send failed: ${error}`, 'error'); return 'not_submitted'; }
    };

    dispose = () => {
        if (this.disposed) return;
        this.disposed = true;
        this.state = {...this.state, wanted:false};
        this.admitted = false;
        this.clearRetry();
        this.clearHeartbeat();
        this.listeners.clear();
        if (this.socket) this.requestClose(this.socket);
    };
}
