import asyncio
import base64
import json
import logging
import uuid
from itertools import cycle
from typing import Any, AsyncGenerator, Dict, List

from app.schemas.gemini_models import GenerateContentRequest
from app.services.connection_manager import manager
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class RequestOrchestrator:
    """
    Orchestrates requests from API endpoints to frontend clients.
    """
    def __init__(self):
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.stream_queues: Dict[str, asyncio.Queue] = {}
        self.client_iterator = None
        self.current_client_list: List[str] = []

    def _get_next_client_id(self) -> str:
        healthy_clients = manager.get_healthy_client_ids()
        if not healthy_clients:
            raise HTTPException(status_code=503, detail="No available healthy frontend clients.")
        
        if set(healthy_clients) != set(self.current_client_list):
            self.current_client_list = healthy_clients
            self.client_iterator = cycle(self.current_client_list)
        
        if not self.client_iterator:
             self.client_iterator = cycle(self.current_client_list)

        return next(self.client_iterator)

    async def handle_request(self, model_name: str, request: GenerateContentRequest) -> Any:
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        await self._dispatch_request(request_id, "generateContent", model_name, request.model_dump(exclude_none=True))
        try:
            result = await asyncio.wait_for(future, timeout=120)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Request timed out.")
        finally:
            self.pending_requests.pop(request_id, None)

    async def handle_stream_request(self, model_name: str, request: GenerateContentRequest) -> AsyncGenerator[str, None]:
        request_id = str(uuid.uuid4())
        queue = asyncio.Queue()
        self.stream_queues[request_id] = queue
        await self._dispatch_request(request_id, "streamGenerateContent", model_name, request.model_dump(exclude_none=True))
        try:
            while True:
                data = await queue.get()
                if data is None:
                    break
                yield f"data: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            logger.info(f"Stream {request_id} was cancelled by the client.")
        finally:
            self.stream_queues.pop(request_id, None)

    async def handle_file_upload(self, file_content: bytes, file_metadata: dict) -> Any:
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        payload = {"content": base64.b64encode(file_content).decode('utf-8'), "metadata": file_metadata}
        await self._dispatch_request(request_id, "uploadFile", "files", payload)
        try:
            # The frontend will do the polling, here we just wait for the final result
            result = await asyncio.wait_for(future, timeout=300)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="File upload timed out.")
        finally:
            self.pending_requests.pop(request_id, None)

    async def handle_count_tokens(self, model_name: str, request: GenerateContentRequest) -> Any:
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        await self._dispatch_request(request_id, "countTokens", model_name, request.model_dump(exclude_none=True))
        try:
            result = await asyncio.wait_for(future, timeout=60)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Request timed out.")
        finally:
            self.pending_requests.pop(request_id, None)

    async def handle_embed_content(self, model_name: str, request: GenerateContentRequest) -> Any:
        request_id = str(uuid.uuid4())
        future = asyncio.Future()
        self.pending_requests[request_id] = future
        await self._dispatch_request(request_id, "embedContent", model_name, request.model_dump(exclude_none=True))
        try:
            result = await asyncio.wait_for(future, timeout=120)
            return result
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Request timed out.")
        finally:
            self.pending_requests.pop(request_id, None)

    async def _dispatch_request(self, request_id: str, request_type: str, model_name: str, payload: dict):
        selected_client_id = self._get_next_client_id()
        message = {
            "type": request_type,
            "request_id": request_id,
            "model": model_name,
            "payload": payload,
        }
        await manager.send_to_client(selected_client_id, json.dumps(message))

    async def process_websocket_message(self, client_id: str, data: str):
        try:
            message = json.loads(data)
            request_id = message.get("request_id")
            msg_type = message.get("type")
            payload = message.get("payload")

            if not request_id: return

            if msg_type == 'http_response' and request_id in self.pending_requests:
                future = self.pending_requests.pop(request_id)
                future.set_result(payload)
            elif msg_type == 'file_upload_complete' and request_id in self.pending_requests:
                future = self.pending_requests.pop(request_id)
                future.set_result(payload)
            elif msg_type == 'stream_chunk' and request_id in self.stream_queues:
                await self.stream_queues[request_id].put(payload)
            elif msg_type == 'stream_end' and request_id in self.stream_queues:
                await self.stream_queues[request_id].put(None)
            elif msg_type == 'error' and request_id in self.pending_requests:
                 future = self.pending_requests.pop(request_id)
                 future.set_exception(Exception(payload.get("error", "Unknown error")))
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from client {client_id}")
        except Exception as e:
            logger.error(f"Error processing message from {client_id}: {e}")

orchestrator = RequestOrchestrator()