import type { Command } from './types';
import { GoogleGenAI } from "@google/genai";

const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";

async function executeListModels(payload: any) {
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

async function executeGetModel(payload: any) {
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

async function testGeminiConnection(): Promise<string> {
    // The API key is managed by the AI Studio environment.
    // The SDK will use the credentials available in the browser context.
    const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || "" });

    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: 'hello',
    });

    return response.text;
}

export const geminiExecutor = {
  execute: (command: Command): Promise<any> => {
      switch (command.type) {
          case 'listModels':
              return executeListModels(command.payload);
          case 'getModel':
              return executeGetModel(command.payload);
          default:
              const exhaustiveCheck: never = command;
              throw new Error(`Unsupported command type: ${(exhaustiveCheck as any).type}`);
      }
  },
  testGeminiConnection,
};