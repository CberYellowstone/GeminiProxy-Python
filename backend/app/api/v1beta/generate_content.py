import uuid
from typing import Annotated

from app.core import manager
from app.schemas import GenerateContentPayload, GenerateContentResponse
from fastapi import Depends, Path, Request
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
    model: Annotated[str, Path(description="The model to use for content generation.")],
    payload: GenerateContentPayload,
    request: Request,
):
    """
    Non-streaming content generation endpoint.
    Cancellation logic is handled by the ConnectionManager.
    """
    request_id = str(uuid.uuid4())
    async with manager.monitored_proxy_request(request_id, request):
        response_data = await manager.proxy_request(
            command_type="generateContent",
            payload={"model": model, "payload": payload.model_dump(by_alias=True, exclude_none=True)},
            request=request,
            request_id=request_id,
            is_streaming=False,
        )
    return response_data


@router.post(
    "/models/{model}:streamGenerateContent",
    response_class=StreamingResponse,
    name="models.streamGenerateContent",
)
async def stream_generate_content(
    model: Annotated[str, Path(description="The model to use for content generation.")],
    payload: GenerateContentPayload,
    request: Request,
):
    """
    Streaming content generation endpoint.
    Monitoring and cancellation logic is handled by the ConnectionManager.
    """
    request_id = str(uuid.uuid4())
    async def generator():
        async with manager.monitored_proxy_request(request_id, request):
            response_generator = await manager.proxy_request(
                command_type="streamGenerateContent",
                payload={"model": model, "payload": payload.model_dump(by_alias=True, exclude_none=True)},
                request=request,
                request_id=request_id,
                is_streaming=True,
            )
            async for chunk in response_generator:
                yield chunk

    return StreamingResponse(generator())