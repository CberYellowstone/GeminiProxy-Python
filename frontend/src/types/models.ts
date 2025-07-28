interface Model {
  name: string;
  version: string;
  displayName?: string;
  description?: string;
  inputTokenLimit?: number;
  outputTokenLimit?: number;
  supportedGenerationMethods: string[];
  temperature?: number;
  topP?: number;
  topK?: number;
  modelStage?: string;
  maxTemperature?: number;
  thinking?: boolean;
}

interface ListModelsCommandResponse {
  id: string;
  payload: {
    models: Model[];
  };
}

interface GetModelCommandResponse {
  id: string;
  payload: Model;
}

interface ListModelsCommandPayload {
  pageSize?: number;
  pageToken?: string;
}

interface ListModelsCommand {
  id: string;
  type: 'listModels';
  payload: ListModelsCommandPayload;
}

interface GetModelCommand {
  id: string;
  type: 'getModel';
  payload: {
    name: string;
  };
}

interface GetModelCommandPayload {
  name: string;
}

export type {
  GetModelCommand,
  GetModelCommandPayload,
  GetModelCommandResponse,
  ListModelsCommand,
  ListModelsCommandPayload,
  ListModelsCommandResponse,
  Model
};

