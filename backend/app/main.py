import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager

from app.api import api_router
from app.core import manager
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import format_response_log
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from rich.logging import RichHandler
from rich.markup import escape


class PingPongFilter(logging.Filter):
    """过滤 WebSocket ping/pong keepalive 日志"""

    def filter(self, record: logging.LogRecord) -> bool:
        # 过滤包含 ping/pong/keepalive 关键词的日志
        message = record.getMessage().lower()
        if any(keyword in message for keyword in ["ping", "pong", "keepalive"]):
            return False
        return True


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "ping_pong_filter": {
            "()": PingPongFilter,
        },
    },
    "handlers": {
        "rich": {
            "class": "rich.logging.RichHandler",
            "rich_tracebacks": True,
            "markup": True,
            "log_time_format": "[%Y-%m-%d %H:%M:%S]",
            "filters": ["ping_pong_filter"],
        },
    },
    "loggers": {
        "": {  # Root logger
            "handlers": ["rich"],
            "level": settings.LOG_LEVEL,
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["rich"],
            "level": settings.LOG_LEVEL,
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["rich"],
            "level": settings.LOG_LEVEL,
            "propagate": False,
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logging.info(f"应用启动 | 环境: {settings.APP_ENV} | 日志级别: {settings.LOG_LEVEL}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    cleanup_task = asyncio.create_task(file_manager.periodic_cleanup_task())
    yield
    # Shutdown
    cleanup_task.cancel()
    file_manager.cleanup_all_temp_files()


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


# PNA
@app.middleware("http")
async def add_pna_header(request: Request, call_next):
    response = await call_next(request)
    if request.method == "OPTIONS":
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.exception_handler(ApiException)
async def api_exception_handler(request: Request, exc: ApiException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(exc.errors())
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
            logging.debug(f"Received full data object: {data}")
            request_id = data.get("id")
            logging.info(
                format_response_log(
                    "browser_to_backend",
                    request_id,
                    f"来自客户端 [bold cyan]{client_id}[/bold cyan] | " f"数据: [grey50]{escape(str(data))}[/grey50]",
                )
            )
            await manager.handle_message(data)  # 将消息交给管理器处理

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logging.error(f"Error in WebSocket for client {client_id}: {e}")
        await manager.disconnect(client_id)
