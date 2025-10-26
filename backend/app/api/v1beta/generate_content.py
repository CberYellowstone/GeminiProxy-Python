from typing import Annotated

from app.core import manager
from app.schemas import GenerateContentPayload, GenerateContentResponse
from fastapi import Path
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter

router = APIRouter(tags=["Generating content"])


@router.post(
    "/models/{model}:generateContent",
    response_model=GenerateContentResponse,
    response_model_exclude_none=True,
    name="models.generateContent",
)
async def generate_content(
    model: Annotated[str, Path(description="The model to use for content generation.")], payload: GenerateContentPayload
):
    response_data = await manager.proxy_request(
        command_type="generateContent", payload={"model": model, "payload": payload.model_dump(by_alias=True, exclude_none=True)}
    )
    return response_data


@router.post(
    "/models/{model}:streamGenerateContent",
    response_class=StreamingResponse,
    name="models.streamGenerateContent",
)
async def stream_generate_content(
    model: Annotated[str, Path(description="The model to use for content generation.")], payload: GenerateContentPayload
):
    response_generator = await manager.proxy_request(
        command_type="streamGenerateContent",
        payload={"model": model, "payload": payload.model_dump(by_alias=True, exclude_none=True)},
        is_streaming=True,
    )
    return StreamingResponse(response_generator)
