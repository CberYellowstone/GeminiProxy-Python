
import { ApiError } from './errors/ApiError';
import { geminiExecutor } from './geminiExecutor/geminiExecutor';
import type { Command, ErrorPayload, ResponsePayload } from './types/types';

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

// Helper to safe-stringify payload for logging (truncate long strings)
const getSafePayloadLog = (obj: any) => {
  if (!obj) return 'null';
  try {
    return JSON.stringify(obj, (key, value) => {
      if (typeof value === 'string' && value.length > 200) {
        return value.substring(0, 200) + '... [TRUNCATED]';
      }
      return value;
    }, 2);
  } catch (e) {
    return '[Circular or Invalid JSON]';
  }
};

const createErrorResponse = (error: unknown, command: Command | null): ErrorPayload => {
  const responseId = command?.id || 'unknown';
  let response: ErrorPayload;
  let logMessage = '';

  if (error instanceof ApiError) {
    // detailed API error
    const apiDetails = error.body ? JSON.stringify(error.body, null, 2) : error.message;
    logMessage = `API Error (${error.status}): ${apiDetails}`;
    
    response = {
      id: responseId,
      status: {
        error: true,
        code: error.status,
        errorPayload: error.body,
      },
    };
  } else {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logMessage = `Error processing command: ${errorMessage}`;
    
    response = {
      id: responseId,
      status: {
        error: true,
        code: 500,
      },
    };
  }

  // Append the request payload to the log for debugging
  if (command) {
    logMessage += `\nFAILED REQUEST PAYLOAD:\n${getSafePayloadLog(command.payload)}`;
  }

  callbacks?.onLog(logMessage);
  return response;
};

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
      const message = JSON.parse(event.data);
      
      // Handle cancel task
      if (message.type === 'cancel_task') {
        const requestId = message.id;
        callbacks?.onLog(`Received cancel request for: ${requestId}`);
        
        const cancelled = geminiExecutor.cancelExecution(requestId);
        
        if (!cancelled) {
          callbacks?.onLog(`Request ${requestId} was not active or already completed`);
        }
        return;
      }
      
      command = message as Command;
      callbacks?.onLog(`Received command: ${command.type} (ID: ${command.id})`);
      
      // --- DEBUG: Log Incoming Payload ---
      console.log(`[Request ${command.id}] Payload:`, command.payload);
      callbacks?.onLog(`Params: ${getSafePayloadLog(command.payload)}`);
      // -----------------------------------

      const sendResponse = (payload: unknown) => {
        // --- DEBUG LOGGING FOR STREAMS ---
        if (command?.type === 'streamGenerateContent') {
          const p = payload as any;
          if (p && p.chunk) {
            // 1. Log full chunk to browser console for detailed inspection
            console.log(`[StreamChunk ${command.id}]`, p.chunk);
            
            // 2. Log truncated snippet to UI Event Log to avoid spamming/lagging
            const chunkStr = typeof p.chunk === 'string' ? p.chunk : JSON.stringify(p.chunk);
            const preview = chunkStr.replace(/\n/g, ' ').substring(0, 60);
            const ellipsis = chunkStr.length > 60 ? '...' : '';
            callbacks?.onLog(`[Stream] Chunk: ${preview}${ellipsis}`);
          } else if (p && p.is_finished) {
             callbacks?.onLog(`[Stream] Finished signal received.`);
          }
        }
        // ---------------------------------

        const response = { id: command?.id, payload };
        let attempts = 0;
        const maxAttempts = 5; // Reduced attempts, faster fail

        const trySend = () => {
            try {
                if (ws) {
                    ws.send(JSON.stringify(response));
                    // Only log success for the "finished" signal or non-stream to avoid spam
                    if (command?.type !== 'streamGenerateContent' || (payload as any).is_finished) {
                        callbacks?.onLog(`Successfully sent response for ID: ${command?.id}`);
                    }
                    return; // Success!
                }
            } catch (e) {
                console.error("Send failed, retrying...", e);
            }

            // Retry logic
            if (attempts < maxAttempts) {
                attempts++;
                setTimeout(trySend, 200); // Faster retry interval (200ms)
            } else {
                 callbacks?.onLog(`WARNING: Dropped streaming response for ID ${command?.id}.`);
            }
        };
        
        trySend();
      };

      // Calculate backend base URL for handling relative paths in commands
      let backendUrl = '';
      try {
        const urlObj = new URL(websocketUrl);
        const protocol = urlObj.protocol === 'wss:' ? 'https:' : 'http:';
        backendUrl = `${protocol}//${urlObj.host}`;
      } catch (e) {
        console.error("Could not parse WebSocket URL for backend origin", e);
      }

      if (command.type === 'streamGenerateContent') {
        await geminiExecutor.execute(command, sendResponse, backendUrl);
        callbacks?.onLog(`Finished streaming for command ID: ${command.id}`);
      } else {
        const result = await geminiExecutor.execute(command, sendResponse, backendUrl);
        
        // --- DEBUG: Log Execution Result ---
        console.log(`[Response ${command.id}] Result:`, result);
        callbacks?.onLog(`Result: ${getSafePayloadLog(result)}`);
        // -----------------------------------
        
        const response: ResponsePayload = { id: command.id, payload: result, status: { error: false, code: 200 } };
        
        // Optimistic send logic: Just try to send it immediately.
        // Don't wait for readyState === OPEN in a loop, as it causes latency if state is flaky.
        let attempts = 0;
        const maxAttempts = 5; 
        
        const trySendSuccess = () => {
             try {
                if (ws) {
                    ws.send(JSON.stringify(response));
                    callbacks?.onLog(`Successfully executed command ID: ${command?.id}`);
                    return;
                }
             } catch (e) {
                console.error("Send success response failed, retrying...", e);
             }
             
             if (attempts < maxAttempts) {
                attempts++;
                setTimeout(trySendSuccess, 200);
             } else {
                callbacks?.onLog(`CRITICAL: Could not send success response for ID ${command?.id} after retries.`);
             }
        };
        trySendSuccess();
      }
    } catch (error) {
      const response = createErrorResponse(error, command);
      const responseId = response.id;
      
      // Optimistic send for error response
      let attempts = 0;
      const maxAttempts = 5;
      
      const trySendError = () => {
        try {
            if (ws) {
                ws.send(JSON.stringify(response));
                callbacks?.onLog(`Sent error response for command ID: ${responseId}`);
                return;
            }
        } catch (e) {
            console.error("Send error response failed, retrying...", e);
        }
        
        if (attempts < maxAttempts) {
            attempts++;
            setTimeout(trySendError, 200);
        } else {
            console.error("Failed to send error response via WebSocket:", response);
            callbacks?.onLog(`CRITICAL: Could not send error response for ID ${responseId}.`);
        }
      };
      trySendError();
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
