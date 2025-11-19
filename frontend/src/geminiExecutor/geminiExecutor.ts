import { GoogleGenAI } from "@google/genai";
import type { CreateFilePayload, DeleteFilePayload, GetFilePayload, UpdateFilePayload } from '../types/files';
import type { generateContentCommand, StreamGenerateContentCommand } from '../types/generatingContent';
import type { GetModelCommandPayload, ListModelsCommandPayload } from '../types/models';
import type { Command } from '../types/types';
import { createMetadataOnlyFile, deleteFile, getFile, initiateResumableUpload, uploadChunk } from "./files";
import { executeGenerateContent, executeStreamGenerateContent } from "./generatingContent";
import { executeGetModel, executeListModels } from './models';

export const GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta";
export const ai = new GoogleGenAI({ apiKey: process.env.API_KEY || "" });

// Manages active requests for cancellation
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
  execute: async (command: Command, sendResponse: (payload: unknown) => void, backendUrl?: string): Promise<any> => {
    switch (command.type) {
      case 'listModels':
        return executeListModels(command.payload as ListModelsCommandPayload);
      case 'getModel':
        return executeGetModel(command.payload as GetModelCommandPayload);
      case 'generateContent':
        return executeGenerateContent(command as generateContentCommand, activeRequests);
      case 'streamGenerateContent':
        await executeStreamGenerateContent(command as StreamGenerateContentCommand, sendResponse, activeRequests);
        return;
      // File API Commands
      case 'createFile':
      case 'initiate_resumable_upload':
        return initiateResumableUpload(command.payload as CreateFilePayload);
      case 'create_file_metadata':
      case 'createFileMetadata':
        return createMetadataOnlyFile(command.payload as CreateFilePayload);
      case 'updateFile':
      case 'upload_chunk':
      case 'upload_file_chunk':
        return uploadChunk(command.payload as UpdateFilePayload, backendUrl);
      case 'getFile':
      case 'get_file':
        return getFile(command.payload as GetFilePayload);
      case 'deleteFile':
      case 'delete_file':
        return deleteFile(command.payload as DeleteFilePayload);
      default:
        const exhaustiveCheck: never = command;
        throw new Error(`Unsupported command type: ${(exhaustiveCheck as any).type}`);
    }
  },
  
  // Cancel execution method
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

// Export activeRequests for testing
export { activeRequests };
