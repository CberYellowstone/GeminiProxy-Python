import time
import uuid
from typing import Any, Dict, List, Optional

from app.schemas.gemini_models import CachedContent, UpdateCachedContentRequest
from fastapi import APIRouter, Body, Depends, HTTPException

db_cached_contents: Dict[str, CachedContent] = {}

router = APIRouter()

@router.post("/v1beta/cachedContents", response_model=CachedContent)
async def create_cached_content(content: Dict[str, Any] = Body(...)):
    content_id = f"cachedContents/{uuid.uuid4()}"
    new_content = CachedContent(
        name=content_id,
        displayName=content.get("displayName"),
        model=content.get("model", ""),
        expireTime=content.get("expireTime")
    )
    db_cached_contents[content_id] = new_content
    return new_content

@router.get("/v1beta/cachedContents/{content_id:path}", response_model=CachedContent)
async def get_cached_content(content_id: str):
    if content_id not in db_cached_contents:
        raise HTTPException(status_code=404, detail="Cached content not found")
    return db_cached_contents[content_id]

@router.get("/v1beta/cachedContents", response_model=List[CachedContent])
async def list_cached_contents():
    return list(db_cached_contents.values())

@router.patch("/v1beta/cachedContents/{content_id:path}", response_model=CachedContent)
async def update_cached_content(content_id: str, updates: UpdateCachedContentRequest):
    if content_id not in db_cached_contents:
        raise HTTPException(status_code=404, detail="Cached content not found")
    
    stored_item = db_cached_contents[content_id]
    update_data = updates.model_dump(exclude_unset=True)
    
    # Pydantic V2 uses model_copy
    updated_item = stored_item.model_copy(update=update_data)
    
    db_cached_contents[content_id] = updated_item
    return updated_item

@router.delete("/v1beta/cachedContents/{content_id:path}", status_code=204)
async def delete_cached_content(content_id: str):
    if content_id not in db_cached_contents:
        raise HTTPException(status_code=404, detail="Cached content not found")
    del db_cached_contents[content_id]
    return {}