from pydantic import BaseModel, Field


class Model(BaseModel):
    name: str
    version: str
    display_name: str = Field(alias="displayName")
    description: str | None = None
    input_token_limit: int = Field(alias="inputTokenLimit")
    output_token_limit: int = Field(alias="outputTokenLimit")
    supported_generation_methods: list[str] | None = Field(alias="supportedGenerationMethods", default=None)
    temperature: float | None = None
    top_p: float | None = Field(alias="topP", default=None)
    top_k: int | None = Field(alias="topK", default=None)
    model_stage: str | None = Field(alias="modelStage", default=None)
    max_temperature: float | None = Field(alias="maxTemperature", default=None)
    thinking: bool | None = None

    class Config:
        # 允许使用别名进行赋值
        populate_by_name = True


# 定义 list 方法的响应体
class ListModelsResponse(BaseModel):
    models: list[Model] | None = None
    next_page_token: str | None = Field(alias="nextPageToken", default=None)

    class Config:
        populate_by_name = True


# 定义 list 方法的请求体
class ListModelsPayload(BaseModel):
    page_size: int | None = Field(None, alias="pageSize")
    page_token: str | None = Field(None, alias="pageToken")

    class Config:
        populate_by_name = True


# 定义 get 方法的请求体
class GetModelPayload(BaseModel):
    name: str
