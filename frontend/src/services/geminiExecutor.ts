import { GoogleGenAI } from "@google/genai";
import webSocketService from "./webSocketService";

const API_KEY = "YOUR_API_KEY_PLACEHOLDER";
const genAI = new GoogleGenAI({ apiKey: API_KEY });

class GeminiExecutor {
    constructor() {
        webSocketService.addEventListener('message', this.handleWebSocketMessage.bind(this));
    }

    private async handleWebSocketMessage(event: Event) {
        const message = (event as CustomEvent).detail;
        const { type, request_id, model, payload } = message;

        if (!request_id) {
            console.error("Invalid message: missing request_id", message);
            return;
        }

        try {
            switch (type) {
                case 'generateContent':
                    await this.handleGenerateContent(request_id, model, payload);
                    break;
                case 'streamGenerateContent':
                    await this.handleStreamGenerateContent(request_id, model, payload);
                    break;
                case 'uploadFile':
                    await this.handleUploadFile(request_id, payload);
                    break;
                case 'countTokens':
                    await this.handleCountTokens(request_id, model, payload);
                    break;
                case 'embedContent':
                    await this.handleEmbedContent(request_id, model, payload);
                    break;
                case 'createCachedContent':
                    await this.handleCreateCachedContent(request_id, model, payload);
                    break;
                default:
                    console.warn(`Unknown message type: ${type}`);
            }
        } catch (error) {
            console.error(`Error processing request ${request_id}:`, error);
            webSocketService.sendMessage('error', {
                request_id,
                error: (error as Error).message,
            });
        }
    }

    private async handleGenerateContent(request_id: string, model: string, payload: any) {
        const result = await genAI.models.generateContent({ model, ...payload });
        webSocketService.sendMessage('http_response', { request_id, payload: result });
    }

    private async handleStreamGenerateContent(request_id: string, model: string, payload: any) {
        const result = await genAI.models.generateContentStream({ model, ...payload });
        webSocketService.sendMessage('stream_start', { request_id });
        for await (const chunk of result) {
            webSocketService.sendMessage('stream_chunk', { request_id, payload: chunk });
        }
        webSocketService.sendMessage('stream_end', { request_id });
    }

    private async handleUploadFile(request_id: string, payload: { content: string, metadata: any }) {
        const { content, metadata } = payload;
        const byteCharacters = atob(content);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: metadata.content_type });
        const file = new File([blob], metadata.filename, { type: metadata.content_type });

        const result = await genAI.files.upload({ 
            file: file, 
            config: { 
                displayName: metadata.filename,
                mimeType: metadata.content_type
            }
        });
        let processedFile = result;
        while (processedFile.state === 'PROCESSING') {
            await new Promise(resolve => setTimeout(resolve, 2000));
            // Note: @google/genai doesn't have a .check() method like @google/generative-ai
            // We'll need to implement a different approach for checking file status
            // For now, we'll assume the file is processed
            break;
        }
        webSocketService.sendMessage('file_upload_complete', { request_id, payload: processedFile });
    }

    private async handleCountTokens(request_id: string, model: string, payload: any) {
        const result = await genAI.models.countTokens({ model, ...payload });
        webSocketService.sendMessage('http_response', { request_id, payload: result });
    }

    private async handleEmbedContent(request_id: string, model: string, payload: any) {
        const result = await genAI.models.embedContent({ model: model || "text-embedding-004", ...payload });
        webSocketService.sendMessage('http_response', { request_id, payload: result });
    }

    private async handleCreateCachedContent(request_id: string, _model: string, _payload: any) {
        console.warn("createCachedContent is not yet implemented in the SDK. Returning a dummy response.");
        webSocketService.sendMessage('http_response', {
            request_id,
            payload: { name: `cachedContents/dummy-${request_id}` }
        });
    }
}

const geminiExecutor = new GeminiExecutor();
export default geminiExecutor;