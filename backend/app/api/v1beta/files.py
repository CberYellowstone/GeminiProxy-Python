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
from app.schemas.gemini_files import File, ListFilesPayload, ListFilesResponse
from fastapi import (
    APIRouter,
    Depends,
    File as FastAPIFile,
    HTTPException,
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


# ============================================================================
# 文件上传 (新方案)
# ============================================================================


@router.post(
    "/files:upload",
    response_model=File,
    name="files.upload",
)
async def upload_file(
    request: Request,
    file: UploadFile = FastAPIFile(...),
):
    """
    上传文件到后端缓存，并触发到 Gemini 的同步上传。
    如果文件已存在，则直接返回现有文件信息。
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"文件上传请求 | {file.filename}")

    # 1. 保存文件到本地缓存并计算 sha256
    try:
        sha256, file_path = await file_manager.save_file_to_cache(file)
    except Exception as e:
        Logger.error("保存文件到缓存失败", exc=e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save file to cache.",
        )

    # 2. 检查文件是否已存在
    entry = file_manager.get_metadata_entry(sha256)
    if entry:
        # 文件已存在，找到一个已同步的客户端并返回其文件信息
        for client_id, data in entry.replication_map.items():
            if data.get("status") == "synced":
                Logger.api_response(request_id, f"文件已存在 (sha256: {sha256[:8]})")
                return File.model_validate(data)
        # 如果存在但没有一个同步成功，则进入下面的首次上传逻辑

    # 3. 首次上传或无同步副本
    if not entry:
        entry = file_manager.create_metadata_entry(sha256, file_path, file)

    # 4. 选择一个客户端进行同步上传
    # (这里的具体逻辑将在步骤7-9中实现，暂时用一个 placeholder)
    # TODO: 替换为新的请求处理函数
    async with manager.monitored_proxy_request(request_id, request) as client_id:
        # a. 为 WebSocket 客户端生成一次性下载令牌
        # 注意：在方案B中，我们需要一种新的令牌机制，暂时复用旧的
        token = "placeholder_token"  # Placeholder
        download_url = f"{settings.PROXY_BASE_URL}/files/internal/{sha256}/{token}:download"

        # b. 指挥客户端上传
        try:
            response_payload = await manager.proxy_request(
                command_type="upload_from_url",
                payload={
                    "download_url": download_url,
                    "file_metadata": {
                        "name": entry.original_filename,
                        "displayName": entry.original_filename,
                        "mimeType": entry.mime_type,
                    },
                },
                request=request,
                request_id=request_id,
                client_id=client_id, # 需要改造 proxy_request 以接受指定 client_id
            )
            gemini_file = response_payload.get("file")
            if not gemini_file:
                raise ApiException(status_code=500, detail="Frontend did not return a file object.")

            # c. 更新元数据
            file_manager.update_replication_status(
                sha256, client_id, "synced", gemini_file
            )
            Logger.api_response(request_id, f"文件同步上传成功 | {client_id}")
            return File.model_validate(gemini_file)

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
    # TODO: 实现基于新元数据结构的分页逻辑
    all_files = []
    for entry in file_manager.metadata_store.values():
        # 返回每个文件最新的一个有效副本
        for data in entry.replication_map.values():
            if data.get("status") == "synced":
                all_files.append(File.model_validate(data))
                break
    return ListFilesResponse(files=all_files)


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
    # TODO: 实现更复杂的删除逻辑
    # 1. 找到 sha256
    # 2. 指挥所有 synced 的客户端删除 Gemini 上的文件
    # 3. 删除本地缓存和元数据
    sha256 = file_manager.get_sha256_by_filename(name)
    if sha256:
        # 这是一个复杂操作，暂时只删除元数据
        file_manager._delete_entry(sha256) # 使用内部方法清理

    return Response(status_code=status.HTTP_204_NO_CONTENT)
