from fastapi import APIRouter

from .v1beta import router as v1beta_router, upload_router

api_router = APIRouter()
api_router.include_router(v1beta_router, prefix="/v1beta")
# 直接添加上传路由以匹配前端的路径期望
api_router.include_router(upload_router, prefix="/upload/v1beta")
