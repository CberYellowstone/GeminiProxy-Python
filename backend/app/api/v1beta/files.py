import json
import logging
import uuid

from app.core import manager
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import Logger
from app.schemas.gemini_files import File, InitialUploadRequest, ListFilesPayload, ListFilesResponse
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
)
from fastapi import Path as FastAPIPath
from fastapi import (
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import FileResponse

# ============================================================================
# 路由器配置
# ============================================================================

router = APIRouter(tags=["Files"])
files_upload_router = APIRouter(tags=["Files"])

# ============================================================================
# 可续传上传端点
# ============================================================================


@files_upload_router.post(
    "/upload/v1beta/files",
    name="files.create",
)
async def create_file(
    request: Request,
    upload_protocol: str = Header(..., alias="X-Goog-Upload-Protocol"),
    upload_command: str = Header(..., alias="X-Goog-Upload-Command"),
    body: InitialUploadRequest = Body(...),
):
    """
    Initializes a resumable upload session for a file. Returns a proxy upload URL for subsequent chunk uploads.
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"文件上传初始化 | {body.file.display_name  or "Unknown"}")

    # 验证上传协议头
    if upload_protocol != "resumable" or upload_command != "start":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resumable upload initiation headers.",
        )

    async with manager.monitored_proxy_request(request_id, request):
        # 向前端发送初始化指令
        response_payload = await manager.proxy_request(
            command_type="initiate_resumable_upload",
            payload={"metadata": body.model_dump(by_alias=True)},
            request=request,
            request_id=request_id,
        )

        # 提取上传 URL
        upload_url = response_payload.get("upload_url")
        if not upload_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Frontend did not return a upload URL.",
            )

        # 创建代理会话(业务逻辑)
        proxy_session_id = file_manager.create_upload_session(upload_url, body)

        # 生成代理上传 URL
        proxy_upload_url = f"{settings.PROXY_BASE_URL}/upload/v1beta/files/{proxy_session_id}:upload"

        # 返回响应
        response = Response(
            headers={
                "X-Goog-Upload-URL": proxy_upload_url,
                "X-Goog-Upload-Status": "active",
            },
        )

        Logger.api_response(request_id, f"会话ID: {proxy_session_id} | 返回上传URL")
        return response


@files_upload_router.post(
    "/upload/v1beta/files/{session_id}:upload",
    name="files.upload",
)
async def update_file(
    request: Request,
    session_id: str = FastAPIPath(..., description="代理上传会话 ID"),
    upload_command: str = Header(..., alias="X-Goog-Upload-Command"),
    content_length: int = Header(..., alias="Content-Length"),
):
    """
    Uploads data chunks for a resumable upload session.
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"文件块上传 | 会话: {session_id[:8]} | {content_length} bytes")

    # 验证会话
    session = file_manager.get_upload_session(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found.")

    # 解析上传偏移量
    try:
        upload_offset = file_manager.extract_upload_offset(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # 保存数据块
    try:
        chunk_path = await file_manager.save_chunk_to_temp_file(session_id, request)
    except (ValueError, IOError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR if isinstance(e, IOError) else status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    # 生成一次性下载令牌
    token = file_manager.generate_chunk_download_token(chunk_path)
    chunk_download_url = f"{settings.PROXY_BASE_URL}/upload/v1beta/files/internal/{token}:download"

    try:
        # 向前端代理请求
        async with manager.monitored_proxy_request(request_id, request):
            response_payload = await manager.proxy_request(
                command_type="upload_chunk",
                payload={
                    "upload_url": session.real_upload_url,
                    "chunk_download_url": chunk_download_url,
                    "upload_command": upload_command,
                    "upload_offset": upload_offset,
                    "content_length": content_length,
                },
                request=request,
                request_id=request_id,
            )

        # 处理响应
        processed = file_manager.process_upload_response(session_id, response_payload)

        # 构造 HTTP 响应
        response = Response(
            status_code=processed["status"],
            content=processed["content"],
            headers=dict(processed["headers"]),
        )

        # 记录日志
        log_detail = f"上传完成" if processed["is_final"] else f"块已接收"
        Logger.api_response(request_id, log_detail)

        return response
    except ApiException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    finally:
        # 清理一次性令牌
        file_manager.invalidate_chunk_download_token(token)


@files_upload_router.get(
    "/upload/v1beta/files/internal/{token}:download",
    include_in_schema=False,
)
async def get_file_chunk(token: str):
    """
    Gets a temporary file chunk for upload to the frontend.
    """
    chunk_path = file_manager.consume_chunk_download_token(token)
    if not chunk_path or not chunk_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found or token invalid.")

    Logger.event("CHUNK_DOWNLOAD", "发送临时文件块给浏览器", token=token[:8])
    return FileResponse(chunk_path, media_type="application/octet-stream")


# ============================================================================
# 文件管理端点
# ============================================================================


@router.get(
    "/files",
    response_model=ListFilesResponse,
    name="files.list",
    response_model_exclude_none=True,
)
async def list_files(params: ListFilesPayload = Depends()):
    """
    Lists the metadata for Files owned by the requesting project.
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"列出文件 | 页大小: {params.page_size}")

    files_response = file_manager.list_files(params.page_size, params.page_token)

    Logger.api_response(request_id, f"{len(files_response.get('files', []))} 个文件")
    return files_response


@router.get(
    "/files/{name:path}",
    name="files.get",
    response_model=File,
    response_model_exclude_none=True,
)
async def get_file(request: Request, name: str):
    """
    Gets the metadata for the given File.
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"获取文件 | {name}")

    async with manager.monitored_proxy_request(request_id, request):
        response_payload = await manager.proxy_request(
            command_type="get_file",
            payload={"file_name": name},
            request=request,
            request_id=request_id,
        )

    file_metadata = File.model_validate(response_payload)
    file_manager.save_file_metadata(file_metadata)  # 更新缓存供 list_files 使用

    Logger.api_response(request_id, f"文件: {name}")
    return file_metadata


@router.delete(
    "/files/{name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    name="files.delete",
)
async def delete_file(request: Request, name: str):
    """
    Deletes the File.
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"删除文件 | {name}")

    try:
        async with manager.monitored_proxy_request(request_id, request):
            await manager.proxy_request(
                command_type="delete_file",
                payload={"file_name": name},
                request=request,
                request_id=request_id,
            )
    except ApiException as e:
        # 如果文件在 Gemini 侧已被删除（404），忽略错误
        if e.status_code != 404:
            raise HTTPException(status_code=e.status_code, detail=e.detail)

    # 删除本地缓存（成功或 404 都删除）
    file_manager.delete_file_metadata(name)

    Logger.api_response(request_id, "删除成功")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
