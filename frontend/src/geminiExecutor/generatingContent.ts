import { ApiError } from '../errors/ApiError';
import type {
  generateContentCommandPayload,
  GenerateContentResponse,
  StreamGenerateContentCommand
} from '../types/generatingContent';
import { GOOGLE_API_URL } from "./geminiExecutor";

async function executeGenerateContent(
  payload: generateContentCommandPayload
): Promise<GenerateContentResponse> {
  const model = payload.model;
  const response = await fetch(`${GOOGLE_API_URL}/models/${model}:generateContent`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload.payload),
  });
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new ApiError(error.error?.message || response.statusText, response.status, error);
  }
  return await response.json();
}

async function executeStreamGenerateContent(
  command: StreamGenerateContentCommand, 
  sendResponse: (payload: unknown) => void,
  activeRequests: Map<string, AbortController>
): Promise<void> {
  const model = command.payload.model;
  const requestId = command.id;
  
  const abortController = new AbortController();
  activeRequests.set(requestId, abortController);
  
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;

  try {
    const response = await fetch(
      `${GOOGLE_API_URL}/models/${model}:streamGenerateContent`, 
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(command.payload.payload),
        signal: abortController.signal,
      }
    );

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    reader = response.body?.getReader();

    if (!reader) {
      throw new Error('Failed to get reader from response body');
    }

    const decoder = new TextDecoder();

    while (true) {
      if (abortController.signal.aborted) {
        console.debug(`Stream for request ${requestId} was aborted (proactive check)`);
        sendResponse({ is_streaming: true, is_finished: true, cancelled: true });
        break;
      }
      const { done, value } = await reader.read();
      if (done) {
        sendResponse({ is_streaming: true, is_finished: true });
        break;
      }
      const chunk = decoder.decode(value, { stream: true });
      sendResponse({ is_streaming: true, chunk, is_finished: false });
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      console.debug(`Stream for request ${requestId} was aborted`);
      sendResponse({ is_streaming: true, is_finished: true, cancelled: true });
    } else {
      console.error('Error in fetch or reading stream:', error);
      sendResponse({ error: error instanceof Error ? error.message : 'Unknown error' });
    }
  } finally {
    if (reader) {
      reader.releaseLock();
    }
    activeRequests.delete(requestId);
    console.debug(`Cleaned up resources for request ${requestId}`);
  }
}

export { executeGenerateContent, executeStreamGenerateContent };

