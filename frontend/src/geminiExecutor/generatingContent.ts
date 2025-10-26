import { ApiError } from '../errors/ApiError';
import type { generateContentCommandPayload, GenerateContentResponse, StreamGenerateContentCommand } from '../types/generatingContent';
import { GOOGLE_API_URL } from "./geminiExecutor";

async function executeGenerateContent(payload: generateContentCommandPayload): Promise<GenerateContentResponse> {
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

async function executeStreamGenerateContent(command: StreamGenerateContentCommand, sendResponse: (payload: unknown) => void): Promise<void> {
  const model = command.payload.model;
  const reader = await fetch(`${GOOGLE_API_URL}/models/${model}:streamGenerateContent`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(command.payload.payload),
  }).then(response => response.body?.getReader());

  if (!reader) {
    throw new Error('Failed to get reader from response body');
  }

  const decoder = new TextDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        sendResponse({ is_streaming: true, is_finished: true });
        break;
      }
      const chunk = decoder.decode(value, { stream: true });
      sendResponse({ is_streaming: true, chunk, is_finished: false });
    }
  } catch (error) {
    console.error('Error reading stream:', error);
    sendResponse({ error: 'Error reading stream' });
  } finally {
    reader.releaseLock();
  }
}

export { executeGenerateContent, executeStreamGenerateContent };

