import asyncio
import logging
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages active WebSocket connections, including health checks.
    """
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.healthy_clients: Set[str] = set()
        self.health_check_task: Optional[asyncio.Task] = None

    async def connect(self, client_id: str, websocket: WebSocket):
        """
        Accepts and stores a new WebSocket connection.
        """
        await websocket.accept()
        self.active_connections[client_id] = websocket
        self.healthy_clients.add(client_id) # Assume healthy on connect
        if self.health_check_task is None:
            self.health_check_task = asyncio.create_task(self._health_check_loop())

    def disconnect(self, client_id: str):
        """
        Removes a WebSocket connection.
        """
        self.active_connections.pop(client_id, None)
        self.healthy_clients.discard(client_id)
        if not self.active_connections and self.health_check_task:
            self.health_check_task.cancel()
            self.health_check_task = None

    async def send_to_client(self, client_id: str, message: str):
        """
        Sends a message to a specific client.
        """
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_text(message)

    def get_all_client_ids(self) -> List[str]:
        return list(self.active_connections.keys())

    def get_healthy_client_ids(self) -> List[str]:
        return list(self.healthy_clients)

    async def _health_check_loop(self):
        while True:
            await asyncio.sleep(30) # Ping every 30 seconds
            for client_id, websocket in list(self.active_connections.items()):
                try:
                    # Send a health check message
                    await asyncio.wait_for(
                        websocket.send_text('{"type": "health_check"}'),
                        timeout=5
                    )
                    self.healthy_clients.add(client_id)
                    logger.debug(f"Client {client_id} passed health check")
                except Exception as e:
                    logger.warning(f"Client {client_id} failed health check: {e}")
                    self.healthy_clients.discard(client_id)
                    try:
                        await websocket.close()
                    except Exception:
                        pass
                    self.disconnect(client_id)

manager = ConnectionManager()