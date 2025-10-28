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
    model: Annotated[str, Path(description="Required. The name of the Model to use for generating the completion.")],
    payload: GenerateContentPayload,
    request: Request,
):
    """
    Generates a model response given an input GenerateContentRequest. Refer to the text generation guide for detailed usage information. Input capabilities differ between models, including tuned models. Refer to the model guide and tuning guide for details.
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
    model: Annotated[str, Path(description="Required. The name of the Model to use for generating the completion.")],
    payload: GenerateContentPayload,
    request: Request,
):
    """
    Generates a streamed response from the model given an input GenerateContentRequest.
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
