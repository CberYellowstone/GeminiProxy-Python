from pydantic import BaseModel, ConfigDict, Field, model_validator

from .gemini_generate_content_schemas import Content, Tool, ToolConfig, UsageMetadata


class CachedContent(BaseModel):
    name: str | None = Field(None, description="Output only. Identifier. The resource name referring to the cached content.")
    display_name: str | None = Field(
        None, alias="displayName", description="Optional. Immutable. The user-generated meaningful display name of the cached content."
    )
    model: str = Field(..., description="Required. Immutable. The name of the Model to use for cached content.")
    contents: list[Content] | None = Field(None, description="Optional. Input only. Immutable. The content to cache.")
    tools: list[Tool] | None = Field(
        None, description="Optional. Input only. Immutable. A list of `Tools` the model may use to generate the next response."
    )
    system_instruction: Content | None = Field(
        None, alias="systemInstruction", description="Optional. Input only. Immutable. Developer set system instruction."
    )
    tool_config: ToolConfig | None = Field(None, alias="toolConfig", description="Optional. Input only. Immutable. Tool config.")
    create_time: str | None = Field(None, alias="createTime", description="Output only. Creation time of the cache entry.")
    update_time: str | None = Field(None, alias="updateTime", description="Output only. When the cache entry was last updated in UTC time.")
    expire_time: str | None = Field(None, alias="expireTime", description="Timestamp in UTC of when this resource is considered expired.")
    ttl: str | None = Field(
        None,
        description="Input only. New TTL for this resource, input only.A duration in seconds with up to nine fractional digits, ending with 's'.",
    )
    usage_metadata: UsageMetadata | None = Field(
        None, alias="usageMetadata", description="Output only. Metadata on the usage of the cached content."
    )

    @model_validator(mode="before")
    def check_expiration_fields(cls, values):
        if values.get("expire_time") is not None and values.get("ttl") is not None:
            raise ValueError("Only one of 'expire_time' or 'ttl' can be set.")
        return values

    model_config = ConfigDict(populate_by_name=True)
