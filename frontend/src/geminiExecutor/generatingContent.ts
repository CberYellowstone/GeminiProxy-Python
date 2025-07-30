import { ApiError } from '../errors/ApiError';
import type { generateContentCommandPayload, GenerateContentResponse } from '../types/generatingContent';
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

export { executeGenerateContent };

