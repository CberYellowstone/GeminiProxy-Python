import asyncio
import logging
import uuid
from typing import Annotated

from app.core import manager
from app.schemas import GenerateContentPayload, GenerateContentResponse
from fastapi import Path, Request
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
    model: Annotated[str, Path(description="The model to use for content generation.")],
    payload: GenerateContentPayload,
    request: Request,
):
    request_id = str(uuid.uuid4())
    
    response_generator = await manager.proxy_request(
        command_type="streamGenerateContent",
        payload={"model": model, "payload": payload.model_dump(by_alias=True, exclude_none=True)},
        is_streaming=True,
        request_id=request_id,
    )
    
    async def monitored_generator():
        try:
            async for chunk in response_generator:
                if await request.is_disconnected():
                    logging.info(f"[DISCONNECT] Client disconnected for {request_id}")
                    await manager.cancel_request(request_id)
                    break
                yield chunk
        except asyncio.CancelledError:
            logging.info(f"[CANCEL] Request {request_id} was cancelled")
            # cancel_request 是幂等的，安全地调用
            await manager.cancel_request(request_id)
            raise
            
    return StreamingResponse(monitored_generator())