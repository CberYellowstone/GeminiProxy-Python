from app.schemas.gemini_models import GenerateContentRequest
from app.services.request_orchestrator import RequestOrchestrator, orchestrator
from fastapi import APIRouter, Depends, Response
from sse_starlette import EventSourceResponse

router = APIRouter()

# This would typically be dynamic, but static is fine for a proxy.
SUPPORTED_MODELS = {
    "gemini-1.5-pro-latest": {
        "name": "models/gemini-1.5-pro-latest",
        "version": "1.0.0",
        "displayName": "Gemini 1.5 Pro",
        "description": "The latest and most advanced model.",
        "inputTokenLimit": 1048576,
        "outputTokenLimit": 8192,
        "supportedGenerationMethods": ["generateContent", "streamGenerateContent", "countTokens", "embedContent"],
    }
}


def get_orchestrator():
    return orchestrator

@router.get("/models")
async def list_models():
    return {"models": list(SUPPORTED_MODELS.values())}

@router.get("/models/{model_name:path}")
async def get_model(model_name: str):
    if model_name in SUPPORTED_MODELS:
        return SUPPORTED_MODELS[model_name]
    return Response(status_code=404)


@router.post("/models/{model_name:path}:generateContent")
async def generate_content(
    model_name: str,
    request: GenerateContentRequest,
    orc: RequestOrchestrator = Depends(get_orchestrator),
):
    return await orc.handle_request(model_name, request)

@router.post("/models/{model_name:path}:streamGenerateContent")
async def stream_generate_content(
    model_name: str,
    request: GenerateContentRequest,
    orc: RequestOrchestrator = Depends(get_orchestrator),
):
    stream_generator = orc.handle_stream_request(model_name, request)
    return EventSourceResponse(stream_generator)

@router.post("/models/{model_name:path}:countTokens")
async def count_tokens(
    model_name: str,
    request: GenerateContentRequest,
    orc: RequestOrchestrator = Depends(get_orchestrator),
):
    return await orc.handle_count_tokens(model_name, request)


@router.post("/models/{model_name:path}:embedContent")
async def embed_content(
    model_name: str,
    request: GenerateContentRequest,
    orc: RequestOrchestrator = Depends(get_orchestrator),
):
    return await orc.handle_embed_content(model_name, request)