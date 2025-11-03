import logging
import uuid

from app.core import manager
from app.core.log_utils import format_request_log, format_response_log
from app.schemas import ListModelsPayload, ListModelsResponse, Model
from fastapi import Depends, Request
from fastapi.routing import APIRouter

router = APIRouter(tags=["Models"])


@router.get(
    "/models",
    response_model=ListModelsResponse,
    response_model_exclude_none=True,
    name="models.list",
)
async def list_models(request: Request, params: ListModelsPayload = Depends()):
    """
    Lists the Models available through the Gemini API.
    """
    request_id = str(uuid.uuid4())
    logging.info(format_request_log("caller_to_backend", request_id, "收到模型列表请求"))
    async with manager.monitored_proxy_request(request_id, request):
        response_data = await manager.proxy_request(
            request=request, request_id=request_id, command_type="listModels", payload=params.model_dump(by_alias=True, exclude_none=True)
        )
    logging.info(format_response_log("backend_to_caller", request_id, f"返回模型列表 | 数量: {len(response_data.get('models', []))}"))
    return response_data


@router.get(
    "/models/{model}",
    response_model=Model,
    response_model_exclude_none=True,
    name="models.get",
)
async def get_model(request: Request, model: str):
    """
    Gets information about a specific Model such as its version number, token limits, parameters and other metadata.
    """
    request_id = str(uuid.uuid4())
    logging.info(format_request_log("caller_to_backend", request_id, f"收到获取模型信息请求 | 模型: [cyan]{model}[/cyan]"))
    command_payload = {"model": model}
    async with manager.monitored_proxy_request(request_id, request):
        response_data = await manager.proxy_request(
            request=request, request_id=request_id, command_type="getModel", payload=command_payload
        )
    logging.info(format_response_log("backend_to_caller", request_id, f"返回模型信息 | 模型: [cyan]{model}[/cyan]"))
    return response_data
