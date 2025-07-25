from venv import logger

from app.core import manager
from app.schemas import GetModelPayload, ListModelsPayload, ListModelsResponse, Model
from fastapi import Path, Query
from fastapi.routing import APIRouter

router = APIRouter(tags=["Models"])


@router.get(
    "/models",
    response_model=ListModelsResponse,
    response_model_exclude_none=True,
)
async def list_models(
    page_size: int | None = Query(
        None,
        alias="pageSize",
        ge=1,
        description="The maximum number of Models to return (per page).",
    ),
    page_token: str | None = Query(
        None,
        alias="pageToken",
        description="A page token, received from a previous models.list call.",
    ),
):
    """
    列出所有可用的模型。
    """
    payload = ListModelsPayload(pageSize=page_size, pageToken=page_token)
    logger.info(f"Listing models with payload: {payload}")
    # 使用管理器代理请求
    response_data = await manager.proxy_request(command_type="listModels", payload=payload)
    return response_data


@router.get(
    "/models/{model_name}",
    response_model=Model,
    response_model_exclude_none=True,
)
async def get_model(model_name: str = Path(..., description="The resource name of the model.")):
    """
    获取指定模型的详细信息。
    """
    payload = GetModelPayload(name=model_name)
    # 使用管理器代理请求
    response_data = await manager.proxy_request(command_type="getModel", payload=payload)
    return response_data
