import { generateContentCommand, GenerateContentResponse, StreamGenerateContentCommand } from './generatingContent';
import type { GetModelCommand, GetModelCommandResponse, ListModelsCommand, ListModelsCommandResponse } from './models';

export type Command = ListModelsCommand | GetModelCommand | generateContentCommand | StreamGenerateContentCommand;

export type ResponsePayload = ListModelsCommandResponse | GetModelCommandResponse | GenerateContentResponse;

export interface ErrorPayload {
  id: string;
  payload?: any;
  status: {
    error: boolean;
    code: number;
    errorPayload?: any;
  }
}

export type BackendResponse = ResponsePayload | ErrorPayload;