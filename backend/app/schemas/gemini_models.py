import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# =================== Common Models ===================

class Part(BaseModel):
    text: Optional[str] = None
    inline_data: Optional[Dict[str, Any]] = Field(None, alias='inlineData')
    file_data: Optional[Dict[str, Any]] = Field(None, alias='fileData')
    # Add other part types like functionCall, functionResponse later

class Content(BaseModel):
    parts: List[Part]
    role: Optional[str] = None

class SafetySetting(BaseModel):
    category: str
    threshold: str

class GenerationConfig(BaseModel):
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    candidate_count: Optional[int] = Field(None, alias='candidateCount')
    max_output_tokens: Optional[int] = Field(None, alias='maxOutputTokens')
    stop_sequences: Optional[List[str]] = Field(None, alias='stopSequences')

class FunctionDeclaration(BaseModel):
    name: str
    description: str
    parameters: Optional[Dict[str, Any]] = None

class Tool(BaseModel):
    function_declarations: Optional[List[FunctionDeclaration]] = Field(None, alias='functionDeclarations')

# =================== Generate Content Models ===================

class GenerateContentRequest(BaseModel):
    contents: List[Content]
    tools: Optional[List[Tool]] = None
    tool_config: Optional[Dict[str, Any]] = Field(None, alias='toolConfig')
    safety_settings: Optional[List[SafetySetting]] = Field(None, alias='safetySettings')
    generation_config: Optional[GenerationConfig] = Field(None, alias='generationConfig')

# Response models will be more complex and added later

# =================== File API Models ===================

class File(BaseModel):
    name: str
    display_name: Optional[str] = Field(None, alias='displayName')
    mime_type: Optional[str] = Field(None, alias='mimeType')
    size_bytes: Optional[str] = Field(None, alias='sizeBytes')
    create_time: Optional[str] = Field(None, alias='createTime')
    update_time: Optional[str] = Field(None, alias='updateTime')
    expiration_time: Optional[str] = Field(None, alias='expirationTime')
    sha256_hash: Optional[str] = Field(None, alias='sha256Hash')
    uri: Optional[str] = None
    state: Optional[str] = None

class UploadFileResponse(BaseModel):
    file: File

# =================== Cached Content Models ===================

class CachedContent(BaseModel):
    name: str
    display_name: Optional[str] = Field(None, alias='displayName')
    model: str
    create_time: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    update_time: str = Field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    expire_time: Optional[str] = Field(None, alias='expireTime')

class UpdateCachedContentRequest(BaseModel):
    display_name: Optional[str] = Field(None, alias='displayName')
    expire_time: Optional[str] = Field(None, alias='expireTime')