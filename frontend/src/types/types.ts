import type { GetModelCommand, GetModelCommandResponse, ListModelsCommand, ListModelsCommandResponse } from './models';

export type Command = ListModelsCommand | GetModelCommand;

export type ResponsePayload = ListModelsCommandResponse | GetModelCommandResponse;

export interface ErrorPayload {
  id: string;
  payload: {
    message: string;
    code: number;
  };
}

export type BackendResponse = ResponsePayload | ErrorPayload;