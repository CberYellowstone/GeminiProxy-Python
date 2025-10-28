import logging
import logging.config

from app.api import api_router
from app.core import manager
from app.core.exceptions import ApiException
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from rich.logging import RichHandler
from rich.markup import escape

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "rich": {
            "class": "rich.logging.RichHandler",
            "rich_tracebacks": True,
            "markup": True,
            "log_time_format": "[%Y-%m-%d %H:%M:%S]",
        },
    },
    "loggers": {
        "": {  # Root logger
            "handlers": ["rich"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["rich"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.access": {
            "handlers": ["rich"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

logging.config.dictConfig(LOGGING_CONFIG)

app = FastAPI(
    title="GeminiProxy-Python",
    description="Manages WebSocket connections and proxies requests to Gemini API via frontend executors.",
)


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
            request_id = data.get("id")
            logging.info(
                f"[bold]Received response for request[/bold] [bold cyan]{request_id}[/bold cyan] "
                f"[bold]from client[/bold] [bold cyan]{client_id}[/bold cyan]. "
                f"Payload: [grey50]{escape(str(data))}[/grey50]"
            )
            await manager.handle_message(data)  # 将消息交给管理器处理

    except WebSocketDisconnect:
        await manager.disconnect(client_id)
    except Exception as e:
        logging.error(f"Error in WebSocket for client {client_id}: {e}")
        await manager.disconnect(client_id)
