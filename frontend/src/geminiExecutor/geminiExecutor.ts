import { GoogleGenAI } from "@google/genai";
import type { Command } from '../types/types';
import { executeGenerateContent, executeStreamGenerateContent } from "./generatingContent";
import { executeGetModel, executeListModels } from './models';

export const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";
export const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || "" });

// 新增：管理活跃请求的 AbortController
const activeRequests = new Map<string, AbortController>();

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
  execute: (command: Command, sendResponse: (payload: unknown) => void): Promise<any> => {
    switch (command.type) {
      case 'listModels':
        return executeListModels(command.payload);
      case 'getModel':
        return executeGetModel(command.payload);
      case 'generateContent':
        return executeGenerateContent(command, activeRequests);
      case 'streamGenerateContent':
        executeStreamGenerateContent(command, sendResponse, activeRequests);
        return Promise.resolve();
      default:
        const exhaustiveCheck: never = command;
        throw new Error(`Unsupported command type: ${(exhaustiveCheck as any).type}`);
    }
  },
  
  // 新增：取消执行方法
  cancelExecution: (requestId: string): boolean => {
    const controller = activeRequests.get(requestId);
    if (controller) {
      controller.abort();
      // No need to delete here, the finally block in executeStreamGenerateContent will handle it.
      console.log(`Aborted request ${requestId}`);
      return true;
    }
    console.warn(`Request ${requestId} not found for cancellation`);
    return false;
  },
  
  testGeminiConnection,
};

// 导出 activeRequests 供测试使用
export { activeRequests };
