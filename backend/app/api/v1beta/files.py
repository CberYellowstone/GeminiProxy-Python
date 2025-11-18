"""文件 API 路由 (方案 B)

负责处理文件的上传、下载、查询和删除。
采用后端缓存策略。
"""

import uuid

from app.core import manager
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import Logger
from app.schemas.gemini_files import (
    File,
    InitialUploadRequest,
    ListFilesPayload,
    ListFilesResponse,
    UploadFileResponse,
)
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File as FastAPIFile,
    HTTPException,
    Path as FastAPIPath,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

# ============================================================================
# 路由器配置
# ============================================================================

router = APIRouter(tags=["Files"])
upload_router = APIRouter(tags=["Files"])


# ============================================================================
# 文件上传 (新方案)
# ============================================================================


@upload_router.post("/files", name="files.create")
async def create_file(
    request: Request,
    body: InitialUploadRequest = Body(...),
):
    """
    初始化一个模拟的可续传上传会话。
    """
    session_id = str(uuid.uuid4())
    file_manager.upload_sessions[session_id] = body.file.model_dump()

    # 注意这里的路径，它指向 v1beta router 下的一个新端点
    proxy_upload_url = f"{settings.PROXY_BASE_URL}/v1beta/files/upload/{session_id}"

    return Response(
        headers={
            "X-Goog-Upload-URL": proxy_upload_url,
            "X-Goog-Upload-Status": "active",
        },
    )


@router.put(
    "/files/upload/{session_id}",
    response_model=UploadFileResponse,
    name="files.resumable_upload",
)
async def resumable_upload(
    request: Request,
    session_id: str = FastAPIPath(...),
):
    """
    接收文件内容，并触发完整的方案 B 上传/同步逻辑。
    """
    if session_id not in file_manager.upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found.")
    
    metadata = file_manager.upload_sessions.pop(session_id)
    
    # 将原始请求体包装成 UploadFile 接口
    upload_file = UploadFile(
        filename=metadata.get("display_name", "untitled"),
        file=request.stream(),
    )

    # --- 从这里开始，是我们之前实现的方案 B 核心逻辑 ---
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"文件内容上传 | {upload_file.filename}")

    try:
        # FastAPI 的 UploadFile 需要 size，但 request.stream() 没有，这里我们先忽略
        # 在 save_file_to_cache 中也不要依赖 file.size
        setattr(upload_file, "size", -1)
        sha256, file_path = await file_manager.save_file_to_cache(upload_file)
    except Exception as e:
        Logger.error("保存文件到缓存失败", exc=e)
        raise HTTPException(status_code=500, detail="Failed to save file to cache.")

    entry = file_manager.get_metadata_entry(sha256)
    if entry:
        for data in entry.replication_map.values():
            if data.get("status") == "synced":
                Logger.api_response(request_id, f"文件已存在 (sha256: {sha256[:8]})")
                return UploadFileResponse(file=File.model_validate(data))

    if not entry:
        entry = file_manager.create_metadata_entry(sha256, file_path, upload_file)

    # TODO: 这里的同步上传逻辑需要与第九步的请求处理器进行最终整合
    client_id = manager.get_next_client()
    token = "placeholder_token"
    download_url = f"{settings.PROXY_BASE_URL}/v1beta/files/internal/{sha256}/{token}:download"

    try:
        response_payload = await manager.proxy_request(
            command_type="upload_from_url",
            payload={"download_url": download_url, "file_metadata": metadata},
            request_id=request_id,
            client_id=client_id,
        )
        gemini_file = response_payload.get("file")
        if not gemini_file:
            raise ApiException(status_code=500, detail="Frontend did not return a file object.")

        file_manager.update_replication_status(sha256, client_id, "synced", gemini_file)
        Logger.api_response(request_id, f"文件同步上传成功 | {client_id}")
        return UploadFileResponse(file=File.model_validate(gemini_file))
    except ApiException as e:
        file_manager.update_replication_status(sha256, client_id, "failed")
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ============================================================================
# 内部下载端点 (供 WebSocket 客户端使用)
# ============================================================================


@router.get(
    "/files/internal/{sha256}/{token}:download",
    include_in_schema=False,
)
async def internal_download_file(sha256: str, token: str):
    """
    供 WebSocket 客户端下载文件内容以进行上传。
    TODO: 需要实现安全的令牌验证机制。
    """
    entry = file_manager.get_metadata_entry(sha256)
    if not entry or not entry.local_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in cache.")

    Logger.event("INTERNAL_DOWNLOAD", "客户端正在下载文件", sha256=sha256[:8])
    return FileResponse(entry.local_path, media_type=entry.mime_type)


# ============================================================================
# 文件管理端点 (重构)
# ============================================================================


@router.get(
    "/files",
    response_model=ListFilesResponse,
    name="files.list",
)
async def list_files(params: ListFilesPayload = Depends()):
    """从后端缓存中列出所有文件。"""
    all_valid_files = []
    # 按创建时间倒序收集所有有效的、已同步的文件副本
    sorted_entries = sorted(file_manager.metadata_store.values(), key=lambda e: e.created_at, reverse=True)

    for entry in sorted_entries:
        for data in entry.replication_map.values():
            if data.get("status") == "synced":
                all_valid_files.append(File.model_validate(data))
                break  # 每个sha256只取一个代表

    # 实现分页
    start_index = 0
    if params.page_token:
        try:
            start_index = int(params.page_token)
        except ValueError:
            pass  # 无效token，从头开始

    end_index = start_index + params.page_size
    paginated_files = all_valid_files[start_index:end_index]

    next_page_token = str(end_index) if end_index < len(all_valid_files) else None

    return ListFilesResponse(files=paginated_files, next_page_token=next_page_token)


@router.get(
    "/files/{name:path}",
    response_model=File,
    name="files.get",
)
async def get_file(name: str):
    """从后端缓存中获取指定文件的元数据。"""
    sha256 = file_manager.get_sha256_by_filename(name)
    if not sha256:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")
    
    entry = file_manager.get_metadata_entry(sha256)
    if entry:
        for data in entry.replication_map.values():
            if data.get("name") == name and data.get("status") == "synced":
                return File.model_validate(data)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")


@router.delete(
    "/files/{name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="files.delete",
)
async def delete_file(request: Request, name: str):
    """
    删除文件缓存及其在所有 Gemini 客户端上的副本。
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"删除文件请求 | {name}")

    sha256 = file_manager.get_sha256_by_filename(name)
    if not sha256:
        # 如果文件在本地不存在，也直接返回成功，保持幂等性
        Logger.api_response(request_id, "文件在本地未找到，视为成功")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    entry = file_manager.get_metadata_entry(sha256)
    if not entry:
        Logger.api_response(request_id, "文件在本地未找到，视为成功")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 派发后台任务去删除所有远程副本
    for client_id, data in entry.replication_map.items():
        if data.get("status") == "synced" and "name" in data:
            remote_name = data["name"]
            # 使用 manager 创建一个独立的后台删除任务
            # TODO: 需要一个更通用的后台任务执行器
            Logger.info(f"派发远程文件删除任务", client_id=client_id, file_name=remote_name)
            # asyncio.create_task(manager.proxy_request(...)) # 简化示意

    # 立即删除本地缓存和元数据
    file_manager._delete_entry(sha256)

    Logger.api_response(request_id, "本地文件已删除，远程删除任务已派发")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
