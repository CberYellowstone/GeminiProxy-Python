import logging
from contextlib import asynccontextmanager

from app.api import api_router
from app.core import manager
from app.core.background_tasks import start_background_tasks, stop_background_tasks
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import Logger, setup_logging
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# 配置日志系统
setup_logging(settings.LOG_LEVEL)
Logger.event("STARTUP", "应用启动", env=settings.APP_ENV, log_level=settings.LOG_LEVEL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await start_background_tasks()
    yield
    # Shutdown
    await stop_background_tasks()
    file_manager.cleanup_all_cache_files()


app = FastAPI(
    title="GeminiProxy-Python",
    description="Manages WebSocket connections and proxies requests to Gemini API via frontend executors.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApiException)
async def api_exception_handler(request: Request, exc: ApiException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    Logger.error("请求验证失败", errors=str(exc.errors()))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=exc.errors(),
    )


app.include_router(api_router)


@app.get("/")
async def read_root():
    """根路径，提供一个简单的健康检查端点"""
    return {
        "status": "ok",
        "connected_clients": list(manager.active_connections.keys()),
    }


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """
    WebSocket 连接的主入口。
    """
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.handle_message(data)  # 统一由 handle_message 处理消息和日志

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        Logger.error("WebSocket 连接异常", exc=e, client_id=client_id)
        await manager.disconnect(client_id)
