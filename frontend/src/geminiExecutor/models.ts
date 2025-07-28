import type { GetModelCommandPayload, ListModelsCommandPayload } from '../types/models';
import { GOOGLE_API_URL } from './geminiExecutor';

async function executeListModels(payload: ListModelsCommandPayload) {
  const params = new URLSearchParams();
  if (payload.pageSize) params.append('pageSize', String(payload.pageSize));
  if (payload.pageToken) params.append('pageToken', String(payload.pageToken));

  const response = await fetch(`${GOOGLE_API_URL}/models?${params.toString()}`, {
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new Error(error.error?.message || response.statusText);
  }
  return await response.json();
}

async function executeGetModel(payload: GetModelCommandPayload) {
  const modelName = payload.name;
  const response = await fetch(`${GOOGLE_API_URL}/models/${modelName}`, {
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: { message: response.statusText } }));
    throw new Error(error.error?.message || response.statusText);
  }
  return await response.json();
}

export { executeGetModel, executeListModels };

