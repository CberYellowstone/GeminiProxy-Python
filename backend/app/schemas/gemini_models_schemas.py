from pydantic import BaseModel, ConfigDict, Field

SUPPORTED_GENERATION_METHODS = (
    "generateContent",
    "countTokens",
    "createCachedContent",
    "batchGenerateContent",
)

class Model(BaseModel):
    name: str = Field(..., description="The resource name of the Model.")
    version: str = Field(..., description="The version number of the model.")
    display_name: str = Field(..., alias="displayName", description="The human-readable name of the model.")
    description: str | None = Field(default=None, description="A short description of the model.")
    input_token_limit: int = Field(alias="inputTokenLimit", description="Maximum number of input tokens allowed for this model.")
    output_token_limit: int = Field(alias="outputTokenLimit", description="Maximum number of output tokens available for this model.")
    supported_generation_methods: list[str] | None = Field(
        alias="supportedGenerationMethods",
        default=None,
        description="The model's supported generation methods.",
        examples=[SUPPORTED_GENERATION_METHODS],
    )
    temperature: float | None = Field(default=None, description="Controls the randomness of the output.")
    top_p: float | None = Field(alias="topP", default=None, description="For Nucleus sampling.")
    top_k: int | None = Field(alias="topK", default=None, description="For Top-k sampling.")
    model_stage: str | None = Field(alias="modelStage", default=None)
    max_temperature: float | None = Field(alias="maxTemperature", default=None, description="The maximum temperature this model can use.")
    thinking: bool | None = Field(default=None, description="Whether the model supports thinking.")

    model_config = ConfigDict(populate_by_name=True)


class ListModelsResponse(BaseModel):
    models: list[Model] | None = Field(default=None, description="The returned Models.")
    next_page_token: str | None = Field(
        alias="nextPageToken", default=None, description="A token, which can be sent as pageToken to retrieve the next page."
    )
    model_config = ConfigDict(populate_by_name=True)


class ListModelsPayload(BaseModel):
    page_size: int | None = Field(None, alias="pageSize", ge=1, description="The maximum number of Models to return (per page).")
    page_token: str | None = Field(None, alias="pageToken", description="A page token, received from a previous models.list call.")

    model_config = ConfigDict(populate_by_name=True)


class GetModelPayload(BaseModel):
    name: str = Field(..., description="The resource name of the model.")
