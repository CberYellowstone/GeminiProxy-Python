import type { generateContentCommandPayload } from '../types/generatingContent';
import { GOOGLE_API_URL } from "./geminiExecutor";

async function executeGenerateContent(payload: generateContentCommandPayload) {
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
    throw new Error(error.error?.message || response.statusText);
  }
  return await response.json();
}

export { executeGenerateContent };

