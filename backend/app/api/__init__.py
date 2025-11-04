from fastapi import APIRouter

from .v1beta import router as v1beta_router
from .v1beta.files import files_upload_router

api_router = APIRouter()
api_router.include_router(v1beta_router, prefix="/v1beta")
api_router.include_router(files_upload_router)
