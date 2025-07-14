import logging

import uvicorn
from app.api.v1beta import cached_contents as v1beta_cached_contents_router
from app.api.v1beta import files as v1beta_files_router
from app.api.v1beta import models as v1beta_models_router
from app.services.connection_manager import manager
from app.services.request_orchestrator import orchestrator
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Gemini API Proxy Server",
    description="A proxy server to relay requests to a frontend running in Google AI Studio.",
    version="0.1.0",
)

# Exception handler for a cleaner error response
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception for {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )

# Include the v1beta routers
app.include_router(v1beta_models_router.router, prefix="/v1beta", tags=["v1beta - Models"])
app.include_router(v1beta_files_router.router, prefix="/v1beta", tags=["v1beta - Files"])
app.include_router(v1beta_cached_contents_router.router, prefix="/v1beta", tags=["v1beta - Cached Contents"])

@app.get("/", tags=["Status"])
async def read_root():
    """Root endpoint to check if the server is running."""
    return {"status": "ok", "message": "Welcome to Gemini API Proxy Server!"}


@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """The WebSocket endpoint for frontend clients to connect to."""
    await manager.connect(client_id, websocket)
    logger.info(f"Client connected: {client_id}")
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received message from {client_id}: {data}")
            await orchestrator.process_websocket_message(client_id, data)
    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {client_id}")
    except Exception as e:
        logger.error(f"Error with client {client_id}: {e}", exc_info=True)
    finally:
        manager.disconnect(client_id)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)