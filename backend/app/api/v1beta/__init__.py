from fastapi import APIRouter

from .models import router as models_router

router = APIRouter()

# 包含 models 模块的路由
router.include_router(models_router)
