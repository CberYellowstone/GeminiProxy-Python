import { v4 as uuidv4 } from 'uuid';

type WebSocketStatus = 'Connecting' | 'Connected' | 'Disconnected' | 'Error';

class WebSocketService extends EventTarget {
    private ws: WebSocket | null = null;
    private client_id: string;
    private url: string;
    private reconnect_interval: number = 5000;

    constructor(baseUrl: string) {
        super();
        this.client_id = uuidv4();
        this.url = `${baseUrl}${this.client_id}`;
        this.connect();
    }

    public getClientId(): string {
        return this.client_id;
    }

    private connect() {
        this.dispatchStatus('Connecting');
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            this.dispatchStatus('Connected');
            this.log('info', 'WebSocket connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                
                // Handle health check messages
                if (message.type === 'health_check') {
                    this.log('info', 'Health check received from server');
                    return; // Don't dispatch health check messages to handlers
                }
                
                this.dispatchEvent(new CustomEvent('message', { detail: message }));
                this.log('received', message);
            } catch (error) {
                this.log('error', 'Failed to parse server message:', event.data);
            }
        };

        this.ws.onclose = () => {
            this.dispatchStatus('Disconnected');
            this.log('warn', 'WebSocket disconnected. Reconnecting...');
            setTimeout(() => this.connect(), this.reconnect_interval);
        };

        this.ws.onerror = (error) => {
            this.dispatchStatus('Error');
            this.log('error', 'WebSocket error:', error);
            this.ws?.close();
        };
    }

    public sendMessage(type: string, payload: any) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const message = { type, payload };
            this.ws.send(JSON.stringify(message));
            this.log('sent', message);
        } else {
            this.log('error', 'WebSocket is not connected.');
        }
    }
    
    private dispatchStatus(status: WebSocketStatus) {
        this.dispatchEvent(new CustomEvent('statusChange', { detail: status }));
    }

    private log(level: 'info' | 'warn' | 'error' | 'sent' | 'received', ...args: any[]) {
        const message = args.map(arg => typeof arg === 'object' ? JSON.stringify(arg, null, 2) : String(arg)).join(' ');

        switch (level) {
            case 'info':
            case 'sent':
            case 'received':
                console.log(...args);
                break;
            case 'warn':
                console.warn(...args);
                break;
            case 'error':
                console.error(...args);
                break;
        }

        const logEntry = { level, message, timestamp: new Date() };
        this.dispatchEvent(new CustomEvent('log', { detail: logEntry }));
    }
}

const webSocketService = new WebSocketService('ws://localhost:8000/ws/');
export default webSocketService;