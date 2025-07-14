from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


class WSRequest(BaseModel):
    """
    Model for requests sent from the backend orchestrator to the frontend executor.
    """
    type: str
    request_id: str = Field(..., alias='requestId')
    model: str
    payload: Dict[str, Any]


class WSResponse(BaseModel):
    """
    Model for responses sent from the frontend executor back to the backend orchestrator.
    """
    type: Literal['http_response', 'file_upload_complete', 'stream_chunk', 'stream_end', 'error']
    request_id: str = Field(..., alias='requestId')
    payload: Dict[str, Any]