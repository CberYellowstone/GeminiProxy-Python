from __future__ import annotations

"""文件 API 路由 (方案 B)

负责处理文件的上传、下载、查询和删除。
采用后端缓存策略。
"""

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
from app.core import manager
from app.core.config import settings
from app.core.file_manager import file_manager
from app.core.log_utils import Logger
from app.core.mime_utils import MimeUtils
from app.schemas.gemini_files import (
    File,
    InitialUploadRequest,
    ListFilesPayload,
    ListFilesResponse,
    UploadFromUrlRequest,
    UploadFileResponse,
)
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File as FastAPIFile,
    HTTPException,
    Path as FastAPIPath,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

# ============================================================================
# 路由器配置
# ============================================================================

router = APIRouter(tags=["Files"])
upload_router = APIRouter(tags=["Files"])


async def fetch_remote_file_metadata(
    request: Request,
    file_name: str,
    parent_request_id: str,
    reason: str = "verify",
    preferred_client_id: Optional[str] = None,
) -> Tuple[Optional[dict], Optional[str]]:
    """
    使用 files.get 命令验证远端的 Gemini 文件元数据。
    返回 (file_dict, client_id)。
    """
    if not file_name:
        return None, None

    verify_request_id = f"{parent_request_id}-{reason}"
    try:
        if preferred_client_id:
            response = await manager.send_command_to_client(
                client_id=preferred_client_id,
                command_type="get_file",
                payload={"file_name": file_name},
                request_id=verify_request_id,
            )
            verify_client_id = preferred_client_id
        else:
            async with manager.monitored_proxy_request(verify_request_id, request) as verify_client_id:
                response = await manager.proxy_request(
                    command_type="get_file",
                    payload={"file_name": file_name},
                    request=request,
                    request_id=verify_request_id,
                )
        remote_file = response.get("file") if isinstance(response, dict) else None
        if not remote_file and isinstance(response, dict):
            remote_file = response
        if remote_file:
            Logger.info(
                "远程文件校验成功",
                request_id=verify_request_id,
                file_name=file_name,
                mime=remote_file.get("mimeType"),
            )
        return remote_file, verify_client_id
    except Exception as exc:
        Logger.warning("远程文件校验失败", request_id=verify_request_id, file_name=file_name, exc=exc)
        return None, None


def build_file_response(
    source_file: Optional[dict],
    entry,
    size_bytes: int,
) -> dict:
    """
    根据远端返回的数据或本地缓存构造 File 响应。
    """
    if source_file:
        try:
            return File.model_validate(source_file).model_dump(by_alias=True, exclude_none=True)
        except ValidationError as exc:
            Logger.warning("远程文件数据无法直接验证，使用本地映射", exc=exc)

    mapped_file_data = map_frontend_response_to_file_model(source_file, entry, size_bytes)
    return File.model_validate(mapped_file_data).model_dump(by_alias=True, exclude_none=True)


def build_final_upload_response(file_data: File | dict) -> JSONResponse:
    """
    构造带有 Google Upload 兼容头部的 JSON 响应
    """
    if isinstance(file_data, File):
        file_obj = file_data
    else:
        file_obj = File.model_validate(file_data)

    payload = UploadFileResponse(file=file_obj).model_dump(by_alias=True, exclude_none=True)
    return JSONResponse(
        content=payload,
        headers={
            "X-Goog-Upload-Status": "final",
            "Content-Type": "application/json",
        },
        status_code=200,
    )


def encode_sha256_base64(sha256_hex: Optional[str]) -> Optional[str]:
    """将十六进制 sha256 转换为 base64 字符串"""
    if not sha256_hex:
        return None
    try:
        return base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")
    except ValueError:
        Logger.warning("无法转换 sha256 为 base64", sha256=sha256_hex)
        return None


def enforce_size_consistency(
    metadata: dict,
    actual_size: int,
    header_size: Optional[str],
    *,
    request_id: str,
    session_id: str,
    file_path: Path,
    check_header: bool = True,
):
    """校验声明的文件大小与实际写入大小是否一致"""
    def _to_int(value, label):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            Logger.warning(f"{label} 不是有效的整数", value=value, request_id=request_id)
            return None

    declared_size = metadata.get("size_bytes") or metadata.get("sizeBytes")
    declared_size_int = _to_int(declared_size, "sizeBytes")
    header_size_int = _to_int(header_size, "Content-Length") if check_header else None

    mismatch_errors = []
    if declared_size_int is not None and declared_size_int != actual_size:
        mismatch_errors.append(
            f"元数据声明大小 {declared_size_int} 与实际大小 {actual_size} 不一致"
        )
    if header_size_int is not None and header_size_int != actual_size:
        mismatch_errors.append(
            f"Content-Length {header_size_int} 与实际大小 {actual_size} 不一致"
        )

    if mismatch_errors:
        try:
            file_path.unlink(missing_ok=True)
        except Exception as cleanup_error:
            Logger.warning("清理不一致的缓存文件失败", exc=cleanup_error, path=str(file_path))
        file_manager.upload_sessions.pop(session_id, None)
        Logger.warning(
            "上传被拒绝，声明大小与实际不符",
            request_id=request_id,
            errors="; ".join(mismatch_errors),
        )
        raise HTTPException(
            status_code=400,
            detail="; ".join(mismatch_errors),
        )


def map_frontend_response_to_file_model(frontend_file: Optional[dict], entry, size_bytes: int) -> dict:
    """
    将前端返回的文件对象映射到后端File模型期望的格式

    Args:
        frontend_file: 前端返回的文件对象
        entry: 文件缓存条目，包含原始文件信息
        size_bytes: 文件大小

    Returns:
        符合File模型格式的字典
    """
    # 确保我们有一个字典可供读取
    frontend_file = frontend_file or {}

    # 创建当前时间戳
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # 构建符合File模型的数据
    fallback_name = f"files/{entry.sha256}"
    sha_base64 = (
        frontend_file.get("sha256Hash")
        or frontend_file.get("sha256_hash")
        or encode_sha256_base64(entry.sha256)
        or entry.sha256
    )
    mapped_file = {
        "name": frontend_file.get("name") or fallback_name,
        "displayName": entry.original_filename or "untitled",
        "mimeType": entry.mime_type or "application/octet-stream",
        "sizeBytes": str(frontend_file.get("size", size_bytes)),
        "createTime": now,
        "updateTime": now,
        "sha256Hash": sha_base64,
        "uri": frontend_file.get("uri") or fallback_name,
        "state": "ACTIVE",  # 假设上传成功后状态为ACTIVE
        "source": "UPLOADED"
    }

    # 如果前端提供了过期时间，使用它
    if "expirationTime" in frontend_file:
        mapped_file["expirationTime"] = frontend_file["expirationTime"]
    elif entry.gemini_file_expiration:
        mapped_file["expirationTime"] = entry.gemini_file_expiration.isoformat().replace('+00:00', 'Z')

    # 如果前端提供了下载URI，使用它
    if "downloadUri" in frontend_file:
        mapped_file["downloadUri"] = frontend_file["downloadUri"]

    return mapped_file


async def _process_cached_file_upload(
    *,
    request: Request,
    sha256: str,
    file_path: Path,
    size_bytes: int,
    metadata: Optional[dict],
    request_id: str,
    session_id: Optional[str],
    filename_hint: Optional[str],
    content_type_hint: Optional[str],
) -> JSONResponse:
    """共享的缓存文件上传处理逻辑"""
    metadata = metadata or {}
    entry = file_manager.get_metadata_entry(sha256)

    if entry:
        for data in entry.replication_map.values():
            if data.get("status") == "synced" and "name" in data:
                try:
                    file_obj = File.model_validate(data)
                    Logger.api_response(request_id, f"文件已存在 (sha256: {sha256[:8]})")
                    if session_id:
                        file_manager.upload_sessions.pop(session_id, None)
                    return build_final_upload_response(file_obj)
                except Exception as e:
                    Logger.warning(f"复制数据不完整，跳过: {e}", request_id=request_id)
                    continue

        fallback_file = build_file_response(None, entry, entry.size_bytes)
        Logger.api_response(request_id, f"文件已存在 (sha256: {sha256[:8]}) | 使用本地元数据")
        if session_id:
            file_manager.upload_sessions.pop(session_id, None)
        return build_final_upload_response(fallback_file)

    normalized_hint = MimeUtils.normalize_filename(filename_hint)
    metadata_filename = MimeUtils.normalize_filename(
        metadata.get("display_name")
        or metadata.get("displayName")
        or metadata.get("filename")
        or metadata.get("fileName")
    )
    valid_names = [
        name for name in [normalized_hint, metadata_filename] if name and name.lower() not in {"untitled", "unknown", "unknown_file"}
    ]
    final_filename = valid_names[0] if valid_names else None

    header_mime = None
    if content_type_hint:
        header_mime = content_type_hint.split(";")[0].strip().lower()
        if header_mime == "application/octet-stream":
            header_mime = None

    metadata_mime = metadata.get("mime_type") or metadata.get("mimeType")
    if isinstance(metadata_mime, str):
        metadata_mime = metadata_mime.strip().lower()

    detected_mime = MimeUtils.detect_mime_type_from_content(file_path)
    inferred_mime_from_name = MimeUtils.infer_mime_type(final_filename) if final_filename else None

    candidate_mimes = [
        header_mime,
        metadata_mime,
        detected_mime,
        inferred_mime_from_name,
    ]
    final_mime = next((mime for mime in candidate_mimes if mime), "application/octet-stream")

    if not final_filename:
        final_filename = MimeUtils.build_fallback_filename(sha256, final_mime)
        Logger.info(f"使用基于类型的临时文件名: {final_filename}", request_id=request_id)
    else:
        suffix = Path(final_filename).suffix
        if not suffix:
            extension = MimeUtils.guess_extension_from_mime(final_mime, default="")
            if extension:
                final_filename = f"{final_filename}{extension}"

    entry = file_manager.create_metadata_entry(
        sha256=sha256,
        file_path=file_path,
        filename=final_filename,
        mime_type=final_mime,
        size_bytes=size_bytes,
    )

    Logger.info(
        f"创建文件元数据 - SHA256: {sha256[:8]}, 文件名: {final_filename}, MIME: {final_mime}",
        request_id=request_id,
    )

    try:
        gemini_file, client_id = await manager.upload_file_from_cache(sha256)
        Logger.api_response(request_id, f"文件同步上传成功 | {client_id}")

        remote_file, verify_client_id = await fetch_remote_file_metadata(
            request,
            gemini_file.get("name"),
            request_id,
            reason="get",
            preferred_client_id=client_id,
        )
        if remote_file:
            file_manager.update_replication_status(
                sha256,
                verify_client_id or client_id,
                "synced",
                remote_file,
            )
            gemini_file = remote_file

        if session_id:
            file_manager.upload_sessions.pop(session_id, None)

        file_data = build_file_response(gemini_file, entry, size_bytes)
        return build_final_upload_response(file_data)
    except HTTPException as e:
        if e.status_code == 503:
            Logger.warning("没有可用的WebSocket客户端连接，但文件已保存到本地缓存", request_id=request_id)
            try:
                local_file_data = {
                    "name": f"files/{sha256}",
                    "displayName": entry.original_filename or "untitled",
                    "mimeType": entry.mime_type or "application/octet-stream",
                    "sizeBytes": str(entry.size_bytes),
                    "createTime": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "updateTime": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    "sha256Hash": encode_sha256_base64(sha256) or sha256,
                    "uri": f"files/{sha256}",
                    "state": "ACTIVE",
                    "source": "UPLOADED",
                }

                file_manager.update_replication_status(sha256, "local", "synced", local_file_data)
                Logger.api_response(request_id, "文件已保存到本地缓存（离线模式）")

                if session_id:
                    file_manager.upload_sessions.pop(session_id, None)

                return build_final_upload_response(local_file_data)
            except Exception as local_error:
                Logger.error("创建本地文件条目失败", exc=local_error, request_id=request_id)

            raise HTTPException(
                status_code=503,
                detail="No frontend clients available. Please ensure the browser client is connected.",
            )
        raise
    except Exception as exc:
        Logger.error("上传过程中发生未预期的错误", exc=exc)
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(exc)}")


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
    metadata = body.file.model_dump(by_alias=True, exclude_none=True) if body and body.file else {}
    file_manager.upload_sessions[session_id] = {
        "metadata": metadata,
        "created_at": datetime.now(timezone.utc),
    }

    # 注意这里的路径，它指向 v1beta router 下的一个新端点
    proxy_upload_url = f"{settings.PROXY_BASE_URL}/v1beta/files/upload/{session_id}"

    return Response(
        headers={
            "X-Goog-Upload-URL": proxy_upload_url,
            "X-Goog-Upload-Status": "active",
        },
    )


@router.post(
    "/files",
    response_model=UploadFileResponse,
    name="files.metadata_create_only",
)
async def create_file_metadata_only(
    request: Request,
    body: InitialUploadRequest = Body(...),
):
    """处理 metadata-only 文件创建请求"""
    request_id = str(uuid.uuid4())
    metadata = body.file.model_dump(by_alias=True, exclude_none=True) if body and body.file else {}
    if not metadata:
        raise HTTPException(status_code=400, detail="file metadata is required")

    Logger.api_request(request_id, "文件 metadata-only 创建")
    payload = {"metadata": {"file": metadata}}
    async with manager.monitored_proxy_request(request_id, request) as client_id:
        response_data = await manager.proxy_request(
            command_type="create_file_metadata",
            payload=payload,
            request=request,
            request_id=request_id,
        )

    remote_file = response_data.get("file") if isinstance(response_data, dict) else None
    if not remote_file and isinstance(response_data, dict):
        remote_file = response_data
    if not isinstance(remote_file, dict):
        raise HTTPException(status_code=502, detail="Invalid response from frontend client")

    entry = file_manager.ensure_remote_entry(remote_file)
    if entry:
        file_manager.update_replication_status(entry.sha256, client_id, "synced", remote_file)

    Logger.api_response(request_id, "metadata-only 文件创建成功")
    return build_final_upload_response(remote_file)


@router.post(
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
    支持自动重试机制以处理临时连接问题。
    """
    if session_id not in file_manager.upload_sessions:
        raise HTTPException(status_code=404, detail="Upload session not found.")

    session_data = file_manager.upload_sessions[session_id]
    metadata = {}
    if isinstance(session_data, dict):
        metadata = session_data.get("metadata", {})
    elif isinstance(session_data, tuple) and len(session_data) == 2:
        metadata = session_data[0]
    else:
        metadata = session_data or {}
    filename = metadata.get("display_name", "untitled")

    # --- 从这里开始，是我们之前实现的方案 B 核心逻辑 ---
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"文件内容上传 | {filename}")

    # 记录关键请求信息
    content_type = request.headers.get("content-type", "unknown")
    content_length = request.headers.get("content-length", "unknown")
    Logger.info(f"文件上传请求 - MIME: {content_type}, 大小: {content_length}", request_id=request_id)

    # 尝试从请求头中获取文件名信息
    content_disposition = request.headers.get('content-disposition', '')
    if content_disposition:
        # 从 Content-Disposition 中解析文件名
        import re
        filename_match = re.search(r'filename[*]?=["\']?([^"\';\s]+)', content_disposition)
        if filename_match:
            filename = filename_match.group(1)
            Logger.info(f"从请求头中提取文件名: {filename}", request_id=request_id)

    # 跳过其他请求头信息处理

    upload_command_header = request.headers.get("x-goog-upload-command", "")
    upload_offset_header = request.headers.get("x-goog-upload-offset")
    command_tokens = {token.strip().lower() for token in upload_command_header.split(",") if token.strip()}
    is_chunked_upload = bool(command_tokens) or upload_offset_header is not None
    finalize_requested = "finalize" in command_tokens

    if is_chunked_upload:
        try:
            upload_offset_int = int(upload_offset_header or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid X-Goog-Upload-Offset header.")

        chunk_data = await request.body()
        try:
            new_offset = file_manager.append_chunk_data(session_id, chunk_data, upload_offset_int)
        except ValueError as offset_error:
            file_manager.discard_chunk_upload(session_id)
            file_manager.upload_sessions.pop(session_id, None)
            raise HTTPException(status_code=400, detail=str(offset_error))

        if not finalize_requested:
            return Response(
                status_code=308,
                headers={
                    "X-Goog-Upload-Status": "active",
                    "X-Goog-Upload-Offset": str(new_offset),
                },
            )

        try:
            sha256, file_path, size_bytes = file_manager.finalize_chunk_upload(session_id)
        except ValueError as finalize_error:
            file_manager.upload_sessions.pop(session_id, None)
            raise HTTPException(status_code=400, detail=str(finalize_error))

        enforce_size_consistency(
            metadata,
            size_bytes,
            header_size=None,
            request_id=request_id,
            session_id=session_id,
            file_path=file_path,
            check_header=False,
        )
    else:
        try:
            body_stream = request.stream()

            async def file_stream():
                async for chunk in body_stream:
                    yield chunk

            sha256, file_path, size_bytes = await file_manager.save_stream_to_cache(
                file_stream(), filename
            )
        except Exception as e:
            Logger.error("保存文件到缓存失败", exc=e)
            raise HTTPException(status_code=500, detail="Failed to save file to cache.")

        enforce_size_consistency(
            metadata,
            size_bytes,
            header_size=request.headers.get("content-length"),
            request_id=request_id,
            session_id=session_id,
            file_path=file_path,
            check_header=True,
        )

    # 统一处理缓存文件
    inferred_name = filename
    if not inferred_name or inferred_name == "untitled":
        content_disposition = request.headers.get("content-disposition", "")
        if content_disposition:
            import re

            filename_match = re.search(r'filename[*]?=["\']?([^"\';\s]+)', content_disposition)
            if filename_match:
                inferred_name = filename_match.group(1)
                Logger.info(f"从请求头推断文件名: {inferred_name}", request_id=request_id)

    return await _process_cached_file_upload(
        request=request,
        sha256=sha256,
        file_path=file_path,
        size_bytes=size_bytes,
        metadata=metadata,
        request_id=request_id,
        session_id=session_id,
        filename_hint=inferred_name,
        content_type_hint=request.headers.get("content-type"),
    )


@router.post(
    "/files:uploadFromUrl",
    response_model=UploadFileResponse,
    name="files.uploadFromUrl",
)
async def upload_file_from_url(
    request: Request,
    payload: UploadFromUrlRequest,
):
    """
    通过远程 URL 下载文件并上传到 Gemini（方案 B）。
    """
    request_id = str(uuid.uuid4())
    Logger.api_request(request_id, f"远程文件上传 | {payload.url}")

    metadata = payload.file.model_dump(by_alias=True, exclude_none=True) if payload.file else {}
    headers = payload.headers or {}

    url_path_name = Path(urlparse(str(payload.url)).path).name or "remote_file"
    filename_hint = (
        metadata.get("display_name")
        or metadata.get("displayName")
        or url_path_name
        or f"remote_{request_id[:8]}"
    )

    effective_filename = filename_hint or url_path_name
    content_type_hint: Optional[str] = None

    try:
        async with httpx.AsyncClient(timeout=settings.REMOTE_DOWNLOAD_TIMEOUT) as client:
            async with client.stream("GET", str(payload.url), headers=headers) as response:
                response.raise_for_status()
                content_type_hint = response.headers.get("content-type")
                disposition = response.headers.get("content-disposition", "")

                remote_filename = None
                if disposition:
                    filename_match = re.search(r'filename[*]?=["\']?([^"\';\s]+)', disposition)
                    if filename_match:
                        remote_filename = filename_match.group(1)

                effective_filename = remote_filename or filename_hint or url_path_name or effective_filename

                async def remote_stream():
                    async for chunk in response.aiter_bytes():
                        if chunk:
                            yield chunk

                sha256, file_path, size_bytes = await file_manager.save_stream_to_cache(remote_stream(), effective_filename)
    except httpx.HTTPError as exc:
        Logger.error("下载远程文件失败", exc=exc, url=str(payload.url), request_id=request_id)
        raise HTTPException(status_code=502, detail=f"Failed to download remote file: {exc}") from exc

    return await _process_cached_file_upload(
        request=request,
        sha256=sha256,
        file_path=file_path,
        size_bytes=size_bytes,
        metadata=metadata,
        request_id=request_id,
        session_id=None,
        filename_hint=effective_filename,
        content_type_hint=content_type_hint,
    )


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
            if data.get("status") == "synced" and "name" in data:
                try:
                    file_obj = File.model_validate(data)
                    all_valid_files.append(file_obj)
                    break  # 每个sha256只取一个代表
                except Exception as e:
                    Logger.warning(f"复制数据不完整，跳过: {e}")
                    continue

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
async def get_file(request: Request, name: str, verify_remote: bool = Query(False, alias="verifyRemote")):
    """从后端缓存中获取指定文件的元数据，可选远程校验。"""
    request_id = str(uuid.uuid4())
    sha256 = file_manager.get_sha256_by_filename(name)
    entry = file_manager.get_metadata_entry(sha256) if sha256 else None

    if not sha256 or not entry:
        remote_file, verify_client_id = await fetch_remote_file_metadata(
            request,
            name,
            request_id,
            reason="get-miss",
        )
        if remote_file:
            remote_entry = file_manager.ensure_remote_entry(remote_file)
            if remote_entry:
                file_manager.update_replication_status(
                    remote_entry.sha256,
                    verify_client_id or "remote",
                    "synced",
                    remote_file,
                )
            return File.model_validate(remote_file)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")

    if verify_remote:
        remote_file, verify_client_id = await fetch_remote_file_metadata(
            request,
            name,
            request_id,
            reason="get",
        )
        if remote_file:
            file_manager.update_replication_status(
                sha256,
                verify_client_id or "remote",
                "synced",
                remote_file,
            )
            return File.model_validate(remote_file)
        Logger.warning("远程校验失败，返回本地缓存", request_id=request_id, file_name=name)

    if entry:
        for data in entry.replication_map.values():
            if data.get("name") == name and data.get("status") == "synced":
                try:
                    return File.model_validate(data)
                except Exception as e:
                    Logger.warning(f"文件数据不完整，无法返回: {e}")
                    continue

    remote_file, verify_client_id = await fetch_remote_file_metadata(
        request,
        name,
        request_id,
        reason="get-refresh",
    )
    if remote_file:
        remote_entry = file_manager.ensure_remote_entry(remote_file)
        if remote_entry:
            file_manager.update_replication_status(
                remote_entry.sha256,
                verify_client_id or "remote",
                "synced",
                remote_file,
            )
        return File.model_validate(remote_file)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found.")


@router.delete(
    "/files/{name:path}",
    status_code=status.HTTP_200_OK,
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
        return JSONResponse(status_code=status.HTTP_200_OK, content={})

    entry = file_manager.get_metadata_entry(sha256)
    if not entry:
        Logger.api_response(request_id, "文件在本地未找到，视为成功")
        return JSONResponse(status_code=status.HTTP_200_OK, content={})

    # 派发后台任务去删除所有远程副本
    for client_id, data in entry.replication_map.items():
        if data.get("status") == "synced" and "name" in data:
            remote_name = data["name"]
            # 使用 manager 创建一个独立的后台删除任务
            Logger.info(f"派发远程文件删除任务", client_id=client_id, file_name=remote_name)
            manager.trigger_delete_task(client_id, remote_name)

    # 立即删除本地缓存和元数据
    file_manager._delete_entry(sha256)

    Logger.api_response(request_id, "本地文件已删除，远程删除任务已派发")
    return JSONResponse(status_code=status.HTTP_200_OK, content={})
