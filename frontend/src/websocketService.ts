import { geminiExecutor } from './geminiExecutor';
import type { Command, BackendResponse, ResponsePayload, ErrorPayload } from './types';

export interface ConnectionCallbacks {
    onOpen: () => void;
    onClose: () => void;
    onError: (event: Event) => void;
    onLog: (message: string) => void;
    onReconnecting: (attempt: number, maxAttempts: number) => void;
    onReconnectSuccess: () => void;
    onReconnectFailed: () => void;
}

let ws: WebSocket | null = null;
let websocketUrl = '';
let clientId = '';
let callbacks: ConnectionCallbacks | null = null;
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;
const reconnectInterval = 3000;
let reconnectTimer: number | null = null;
let isExplicitlyClosed = false;

const connectInternal = () => {
    if (!websocketUrl || !clientId) {
        callbacks?.onLog('WebSocket URL or Client ID is missing.');
        return;
    }
    ws = new WebSocket(`${websocketUrl}/${clientId}`);
    callbacks?.onLog(`Connecting to ${websocketUrl}/${clientId}...`);

    ws.onopen = () => {
        callbacks?.onLog('WebSocket connection established.');
        if (reconnectAttempts > 0) {
            callbacks?.onReconnectSuccess();
        }
        reconnectAttempts = 0;
        if (reconnectTimer) clearTimeout(reconnectTimer);
        reconnectTimer = null;
        callbacks?.onOpen();
    };

    ws.onclose = () => {
        callbacks?.onClose();
        if (isExplicitlyClosed) {
            callbacks?.onLog('WebSocket connection closed by user.');
            return;
        }
        
        if (reconnectAttempts < maxReconnectAttempts) {
            reconnectAttempts++;
            callbacks?.onLog(`Connection lost. Reconnect attempt ${reconnectAttempts}/${maxReconnectAttempts} in ${reconnectInterval / 1000}s...`);
            callbacks?.onReconnecting(reconnectAttempts, maxReconnectAttempts);
            reconnectTimer = window.setTimeout(connectInternal, reconnectInterval);
        } else {
            callbacks?.onLog(`Could not reconnect after ${maxReconnectAttempts} attempts.`);
            callbacks?.onReconnectFailed();
        }
    };

    ws.onerror = (event) => {
        callbacks?.onLog(`WebSocket error. See browser console for details.`);
        callbacks?.onError(event);
    };

    ws.onmessage = async (event) => {
        let command: Command | null = null;
        try {
          command = JSON.parse(event.data) as Command;
          callbacks?.onLog(`Received command: ${command.type} (ID: ${command.id})`);
  
          const sendResponse = (response: BackendResponse) => {
              ws?.send(JSON.stringify(response));
          };
          
          const result = await geminiExecutor.execute(command);
          const response: ResponsePayload = { id: command.id, payload: result };
          sendResponse(response);
          callbacks?.onLog(`Successfully executed command ID: ${command.id}`);
  
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : String(error);
          callbacks?.onLog(`Error processing command: ${errorMessage}`);
          
          const responseId = command?.id || 'unknown';
          const response: ErrorPayload = {
              id: responseId,
              payload: { message: errorMessage, code: 500 },
          };
          ws?.send(JSON.stringify(response));
        }
    };
};

const connect = (url: string, id: string, cbs: ConnectionCallbacks) => {
    websocketUrl = url;
    clientId = id;
    callbacks = cbs;
    reconnectAttempts = 0;
    isExplicitlyClosed = false;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (ws) ws.close();
    connectInternal();
};

const disconnect = () => {
    isExplicitlyClosed = true;

    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    if (ws && ws.readyState !== WebSocket.CLOSED && ws.readyState !== WebSocket.CLOSING) {
        ws.close();
    }
};

const manualReconnect = () => {
    if (ws && ws.readyState === WebSocket.OPEN) return;
    callbacks?.onLog('Manual reconnection initiated.');
    connect(websocketUrl, clientId, callbacks!);
};

export const websocketService = { connect, disconnect, manualReconnect };