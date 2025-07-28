import { generateContentCommand, GenerateContentResponse } from './generatingContent';
import type { GetModelCommand, GetModelCommandResponse, ListModelsCommand, ListModelsCommandResponse } from './models';

export type Command = ListModelsCommand | GetModelCommand | generateContentCommand;

export type ResponsePayload = ListModelsCommandResponse | GetModelCommandResponse | GenerateContentResponse;

export interface ErrorPayload {
  id: string;
  payload: {
    message: string;
    code: number;
  };
}

export type BackendResponse = ResponsePayload | ErrorPayload;