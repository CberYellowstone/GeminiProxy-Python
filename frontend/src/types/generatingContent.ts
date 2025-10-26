import { Candidate, Content, GenerateContentResponsePromptFeedback, GenerationConfig, SafetySetting, Tool, ToolConfig, UsageMetadata } from "@google/genai";

interface generateContentPayload {
    contents: Content[];
    tools?: Tool[];
    toolConfig?: ToolConfig;
    safetySettings?: SafetySetting[];
    systemInstruction?: Content;
    generationConfig?: GenerationConfig;
    cachedContent?: string;
}

interface generateContentCommandPayload {
    model: string;
    payload: generateContentPayload;
}

interface GenerateContentResponse {
    candidates: Candidate[];
    promptFeedback?: GenerateContentResponsePromptFeedback;
    usageMetadata?: UsageMetadata;
    modelVersion?: string;
    responseId?: string;
}

interface generateContentCommandResponse {
    id: string;
    payload: GenerateContentResponse;
  status: {
    error: boolean;
    code: number;
    errorPayload?: any;
  }
}

interface generateContentCommand {
    id: string;
    type: 'generateContent';
    payload: generateContentCommandPayload;
}

export interface StreamGenerateContentCommand {
    id: string;
    type: 'streamGenerateContent';
    payload: generateContentCommandPayload;
}

export type {
  generateContentCommand, generateContentCommandPayload,
  generateContentCommandResponse,
  generateContentPayload,
  GenerateContentResponse
};

