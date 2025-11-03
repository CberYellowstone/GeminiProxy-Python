from fastapi import APIRouter

from .files import router as files_router
from .generate_content import router as generate_content_router
from .models import router as models_router

router = APIRouter()

# 包含 models 模块的路由
router.include_router(models_router)
# 包含 generate_content 模块的路由
router.include_router(generate_content_router)

# 包含 files 模块的路由
router.include_router(files_router)
