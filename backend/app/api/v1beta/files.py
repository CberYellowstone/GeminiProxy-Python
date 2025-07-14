from typing import List

from app.schemas.gemini_models import File as FileSchema
from app.schemas.gemini_models import UploadFileResponse
from app.services.request_orchestrator import RequestOrchestrator, orchestrator
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

router = APIRouter()

# In-memory cache for file metadata and state.
db_files: dict[str, FileSchema] = {}

def get_orchestrator():
    return orchestrator

@router.post("/upload/v1beta/files", response_model=UploadFileResponse)
async def upload_file(
    file: UploadFile = File(...),
    orc: RequestOrchestrator = Depends(get_orchestrator),
):
    """
    Handles file uploads by passing them to a frontend client for processing.
    """
    file_content = await file.read()
    file_metadata = {
        "filename": file.filename,
        "content_type": file.content_type,
    }
    
    # The orchestrator will handle the upload and wait for the final response
    result_file = await orc.handle_file_upload(file_content, file_metadata)
    
    # Store the final file metadata
    file_schema = FileSchema(**result_file)
    db_files[file_schema.name] = file_schema
    
    return {"file": file_schema}

@router.get("/v1beta/files", response_model=List[FileSchema])
async def list_files():
    """
    Lists all uploaded files.
    """
    return list(db_files.values())

@router.get("/v1beta/files/{file_id:path}", response_model=FileSchema)
async def get_file(file_id: str):
    """
    Gets file metadata and state. Used for polling.
    """
    if file_id not in db_files:
        raise HTTPException(status_code=404, detail="File not found")
    # In a real scenario, we might update the state from the orchestrator here
    return db_files[file_id]

@router.delete("/v1beta/files/{file_id:path}", status_code=204)
async def delete_file(file_id: str):
    """
    Deletes a file.
    """
    if file_id not in db_files:
        raise HTTPException(status_code=404, detail="File not found")
    del db_files[file_id]
    return {}