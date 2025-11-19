
import { ApiError } from '../errors/ApiError';
import type {
  generateContentCommand,
  GenerateContentResponse,
  StreamGenerateContentCommand
} from '../types/generatingContent';
import { GOOGLE_API_URL } from "./geminiExecutor";

/**
 * Sanitizes the payload synchronously for obvious issues like relative URIs.
 */
const sanitizePayloadSync = (payload: any) => {
  if (!payload || !payload.contents) return payload;
  const newPayload = JSON.parse(JSON.stringify(payload));

  if (Array.isArray(newPayload.contents)) {
    newPayload.contents.forEach((content: any) => {
      if (Array.isArray(content.parts)) {
        content.parts.forEach((part: any) => {
          if (part.fileData) {
            // Fix fileData fileUri expansion
            if (part.fileData.fileUri && typeof part.fileData.fileUri === 'string') {
              let uri = part.fileData.fileUri;
              
              // We trust the backend/upload API to provide the correct URI.
              // We do NOT expand relative paths (files/...) automatically anymore.
              
              // Fix double 'files/' segments (e.g. .../files/files/xyz)
              if (uri.match(/\/files\/files\//)) {
                  console.warn(`Fixing malformed URI (double files/): ${uri}`);
                  uri = uri.replace(/\/files\/files\//, '/files/');
              }

              part.fileData.fileUri = uri;
            }
          }
        });
      }
    });
  }
  return newPayload;
};

/**
 * Polls the Gemini API until the file state becomes ACTIVE or FAILED.
 * DISABLED for efficiency: Now returns immediately.
 */
async function waitForFileActive(fileUri: string): Promise<any> {
  // Optimization: Bypassing the check completely as requested to remove waiting mechanisms.
  // We assume the file is ready immediately after upload.
  return Promise.resolve({ state: 'ACTIVE' });
  
  /* 
  // OLD LOGIC KEPT FOR REFERENCE IF NEEDED LATER:
  const match = fileUri.match(/files\/[^/?#]+/);
  if (!match) return null;
  
  const resourceName = match[0];
  const cleanResourceName = resourceName.replace(/^files\/files\//, 'files/');
  const url = `${GOOGLE_API_URL}/${cleanResourceName}`;
  
  // ... fetch loop ...
  */
}

/**
 * Async payload fixer.
 * 1. Normalizes URIs.
 * 2. (Skipped) Polls files to ensure they are ACTIVE.
 * 3. Updates MIME types from server metadata (Skipped if polling is disabled).
 */
const fixPayloadAsync = async (payload: any) => {
  const newPayload = sanitizePayloadSync(payload);

  if (Array.isArray(newPayload.contents)) {
    for (const content of newPayload.contents) {
      if (Array.isArray(content.parts)) {
        for (const part of content.parts) {
          // 1. Fix inlineData MIME types
          if (part.inlineData && part.inlineData.mimeType === 'application/octet-stream') {
             part.inlineData.mimeType = 'text/plain';
          }

          // 2. Fix fileData
          if (part.fileData && part.fileData.fileUri) {
             // Since we disabled waitForFileActive, we won't get metadata here.
             // We trust the payload provided by the backend.
             // If strict MIME type checking is needed, re-enable waitForFileActive.
          }
        }
      }
    }
  }
  return newPayload;
};

/**
 * Helper to fetch with retry for 5xx errors
 */
async function fetchWithRetry(url: string, options: RequestInit, signal: AbortSignal): Promise<Response> {
    let attempt = 0;
    const maxRetries = 3; // Aggressive retry count for 500 errors
    
    while (true) {
        attempt++;
        try {
            const response = await fetch(url, { ...options, signal });
            
            if (response.status < 500 && response.status !== 429) {
                return response;
            }
            
            if (attempt > maxRetries) {
                 if (response.status === 500) {
                    throw new Error("Gemini API 500 Internal Error. This often indicates a corrupted uploaded file, or the file index is not yet ready. Please try again in a moment.");
                 }
                 return response; 
            }
            
            console.warn(`Gemini API returned ${response.status}. Retrying attempt ${attempt}/${maxRetries}...`);
            
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') {
                throw e;
            }
            if (attempt > maxRetries) throw e;
            console.warn(`Network error: ${e}. Retrying attempt ${attempt}/${maxRetries}...`);
        }
        
        const delay = Math.pow(2, attempt) * 1000;
        await new Promise(resolve => setTimeout(resolve, delay));
    }
}

async function executeGenerateContent(
  command: generateContentCommand,
  activeRequests: Map<string, AbortController>
): Promise<GenerateContentResponse> {
  const model = command.payload.model;
  const requestId = command.id;

  const abortController = new AbortController();
  activeRequests.set(requestId, abortController);

  try {
    const sanitizedPayload = await fixPayloadAsync(command.payload.payload);

    const response = await fetchWithRetry(
      `${GOOGLE_API_URL}/models/${model}:generateContent`, 
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizedPayload),
      },
      abortController.signal
    );

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
      throw new ApiError(error.error?.message || response.statusText, response.status, error);
    }
    return await response.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      console.debug(`Request ${requestId} was aborted`);
    }
    throw error;
  } finally {
    activeRequests.delete(requestId);
    console.debug(`Cleaned up resources for request ${requestId}`);
  }
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
    const sanitizedPayload = await fixPayloadAsync(command.payload.payload);

    const response = await fetchWithRetry(
      `${GOOGLE_API_URL}/models/${model}:streamGenerateContent`, 
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sanitizedPayload),
      },
      abortController.signal
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
        sendResponse({ is_streaming: true, is_finished: true, cancelled: true });
        break;
      }
      
      const { done, value } = await reader.read();
      
      if (done) {
        const finalChunk = decoder.decode();
        if (finalChunk && finalChunk.length > 0) {
            sendResponse({ is_streaming: true, chunk: finalChunk, is_finished: false });
        }
        sendResponse({ is_streaming: true, is_finished: true });
        break;
      }
      
      const chunk = decoder.decode(value, { stream: true });
      
      if (chunk && chunk.length > 0) {
          sendResponse({ is_streaming: true, chunk, is_finished: false });
      }

      await new Promise(resolve => setTimeout(resolve, 0));
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
