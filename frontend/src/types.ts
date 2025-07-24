export interface ListModelsCommandPayload {
  pageSize?: number;
  pageToken?: string;
}

export interface ListModelsCommand {
  id: string;
  type: 'listModels';
  payload: ListModelsCommandPayload;
}

export interface GetModelCommand {
  id: string;
  type: 'getModel';
  payload: {
    name: string;
  };
}

export type Command = ListModelsCommand | GetModelCommand;

export interface Model {
  name: string;
  version: string;
  displayName: string;
  description?: string;
  inputTokenLimit: number;
  outputTokenLimit: number;
  supportedGenerationMethods: string[];
  temperature?: number;
  topP?: number;
  topK?: number;
  modelStage?: string;
  maxTemperature?: number;
  thinking?: boolean;
}

export interface ListModelsCommandResponse {
  id: string;
  payload: {
    models: Model[];
  };
}

export interface GetModelCommandResponse {
  id: string;
  payload: Model;
}

export type ResponsePayload = ListModelsCommandResponse | GetModelCommandResponse;

export interface ErrorPayload {
  id: string;
  payload: {
    message: string;
    code: number;
  };
}

export type BackendResponse = ResponsePayload | ErrorPayload;