import { GoogleGenAI } from "@google/genai";
import type { Command } from '../types/types';
import { executeGetModel, executeListModels } from './models';

export const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";

// The API key is managed by the AI Studio environment.
// The SDK will use the credentials available in the browser context.
export const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || "" });

async function testGeminiConnection(): Promise<string> {
    const response = await ai.models.generateContent({
      model: 'gemini-2.5-flash',
      contents: 'hello',
    });

  if (!response || !response.text || response.text.trim() === '') {
    throw new Error("No response received from Gemini API.");
  }
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