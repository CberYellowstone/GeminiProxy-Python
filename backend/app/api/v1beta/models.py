from typing import Annotated

from app.core import manager
from app.schemas import GetModelPayload, ListModelsPayload, ListModelsResponse, Model
from fastapi import Path, Query
from fastapi.routing import APIRouter

router = APIRouter(tags=["Models"])


@router.get(
    "/models",
    response_model=ListModelsResponse,
    response_model_exclude_none=True,
    name="models.list",
)
async def list_models(params: Annotated[ListModelsPayload, Query()]):
    """
    Lists the Models available through the Gemini API.
    """
    response_data = await manager.proxy_request(command_type="listModels", payload=params)
    return response_data


@router.get(
    "/models/{name}",
    response_model=Model,
    response_model_exclude_none=True,
    name="models.get",
)
async def get_model(params: Annotated[GetModelPayload, Path()]):
    """
    Gets information about a specific Model such as its version number, token limits, parameters and other metadata.
    """
    response_data = await manager.proxy_request(command_type="getModel", payload=params)
    return response_data
