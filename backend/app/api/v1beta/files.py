import logging
import re
import secrets
import uuid
from pathlib import Path

from app.core import manager
from app.core.config import settings
from app.core.exceptions import ApiException
from app.core.file_manager import file_manager
from app.core.log_utils import format_request_log, format_response_log
from app.schemas.gemini_files import File, InitialUploadRequest
from fastapi import (
    APIRouter,
    Body,
)
from fastapi import File as FastAPIFile
from fastapi import (
    Header,
    HTTPException,
)
from fastapi import Path as FastAPIPath
from fastapi import (
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from rich.markup import escape

router = APIRouter()
upload_router = APIRouter()

# A simple in-memory store for one-time tokens for chunk downloads
chunk_download_tokens: dict[str, Path] = {}


def generate_one_time_token(chunk_path: Path) -> str:
    token = secrets.token_urlsafe(32)
    chunk_download_tokens[token] = chunk_path
    return token


@upload_router.post(
    "/v1beta/files",
    summary="Initializes a resumable file upload session",
    status_code=status.HTTP_200_OK,
)
async def initialize_upload(
    request: Request,
    upload_protocol: str = Header(..., alias="X-Goog-Upload-Protocol"),
    upload_command: str = Header(..., alias="X-Goog-Upload-Command"),
    body: InitialUploadRequest = Body(...),
):
    logging.info(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] "
        f"[bold]收到上传初始化请求[/bold] | 文件: [green]{body.file.display_name}[/green]"
    )
    logging.debug(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] " f"上传初始化请求详细内容: {body.model_dump(by_alias=True)}"
    )
    if upload_protocol != "resumable" or upload_command != "start":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resumable upload initiation headers.",
        )

    request_id = str(uuid.uuid4())
    async with manager.monitored_proxy_request(request_id, request):
        try:
            response_payload = await manager.proxy_request(
                command_type="initiate_resumable_upload",
                payload={"metadata": body.model_dump(by_alias=True)},
                request=request,
                request_id=request_id,
            )
            logging.info(format_response_log("browser_to_backend", request_id, f"收到上传初始化响应 | 数据: {response_payload}"))
            upload_url = response_payload.get("upload_url")
            if not upload_url:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Frontend did not return a upload URL.",
                )
            logging.debug(f"Extracted upload_url: {upload_url}")

            proxy_session_id = file_manager.create_upload_session(upload_url, body.model_dump(by_alias=True))
            logging.debug(f"Created proxy_session_id: {proxy_session_id}")
            proxy_upload_url = f"{settings.PROXY_BASE_URL}/upload/proxy/{proxy_session_id}"
            logging.debug(f"Generated proxy_upload_url: {proxy_upload_url}")

            response = Response(
                status_code=status.HTTP_200_OK,
                headers={
                    "X-Goog-Upload-URL": proxy_upload_url,
                    "X-Goog-Upload-Status": "active",
                },
            )
            logging.info(
                format_response_log(
                    "backend_to_caller",
                    request_id,
                    f"返回上传初始化响应 | 状态: {response.status_code} | " f"代理URL: [blue]{proxy_upload_url}[/blue]",
                )
            )
            return response
        except Exception:
            logging.exception("An unexpected error occurred during upload initialization.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal error occurred.",
            )


@upload_router.post(
    "/proxy/{proxy_session_id}",
    summary="Uploads a file chunk to the proxy",
    status_code=status.HTTP_200_OK,
)
async def upload_chunk(
    request: Request,
    proxy_session_id: str = FastAPIPath(...),
    upload_command: str = Header(..., alias="X-Goog-Upload-Command"),
    content_length: int = Header(..., alias="Content-Length"),
):
    logging.info(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] "
        f"[bold]收到文件块上传[/bold] | 会话: [cyan]{proxy_session_id}[/cyan] | "
        f"大小: {content_length} bytes"
    )
    logging.debug(f"upload_chunk headers: {request.headers}")
    content_range_header = request.headers.get("Content-Range")
    x_goog_upload_offset_header = request.headers.get("X-Goog-Upload-Offset")

    upload_offset = -1

    if content_range_header:
        # e.g., "bytes 100-200/500"
        match = re.search(r"bytes (\d+)-", content_range_header)
        if match:
            upload_offset = int(match.group(1))

    if upload_offset == -1 and x_goog_upload_offset_header is not None:
        try:
            upload_offset = int(x_goog_upload_offset_header)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Goog-Upload-Offset header.",
            )

    if upload_offset == -1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing upload offset information (Content-Range or X-Goog-Upload-Offset).",
        )

    session = file_manager.get_upload_session(proxy_session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found.")

    # Save chunk to a temporary file
    chunk_id = str(uuid.uuid4())
    chunk_path = file_manager.temp_chunks_dir / f"chunk_{chunk_id}.bin"
    session.temp_chunks.append(chunk_path)

    try:
        with open(chunk_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
    except Exception as e:
        logging.error(f"Failed to write chunk to temp file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file chunk.")

    # Generate a one-time download URL for the frontend
    token = generate_one_time_token(chunk_path)
    chunk_download_url = f"{settings.PROXY_BASE_URL}/upload/_internal/chunks/{token}"

    request_id = str(uuid.uuid4())
    async with manager.monitored_proxy_request(request_id, request):
        try:
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

            # Extract status, headers and body from browser response
            response_status = response_payload.get("status", 200)
            response_headers = response_payload.get("headers", {})
            response_body = response_payload.get("body", {})

            # If this was the final chunk, the response will contain the file metadata
            if isinstance(response_body, dict) and "file" in response_body:
                file_metadata = File.model_validate(response_body["file"])
                file_manager.save_file_metadata(file_metadata)
                file_manager.cleanup_session(proxy_session_id)

                # Return the complete response with headers and file metadata body
                import json

                final_response_content = json.dumps(response_body)
                final_response = Response(
                    status_code=response_status,
                    content=final_response_content,
                    headers=dict(response_headers),  # Pass through all headers from Gemini including x-goog-upload-status: final
                )

                logging.info(
                    format_response_log(
                        "backend_to_caller",
                        request_id,
                        f"返回最终块元数据 | 文件: [green]{file_metadata.name}[/green] | "
                        f"状态: {response_status} | 响应头: {dict(response_headers)} | "
                        f"响应体: [grey50]{escape(final_response_content[:200])}...[/grey50]",
                    )
                )
                return final_response

            # For intermediate chunks, pass through the exact response from Gemini API
            # Convert body to string if it's not already
            if isinstance(response_body, dict):
                import json

                response_content = json.dumps(response_body)
            else:
                response_content = str(response_body)

            response = Response(
                status_code=response_status,
                content=response_content,
                headers=dict(response_headers),  # Pass through all headers from Gemini
            )

            logging.info(
                format_response_log(
                    "backend_to_caller",
                    request_id,
                    f"返回块上传响应 | 状态: {response.status_code} | "
                    f"响应头: {dict(response_headers)} | "
                    f"数据: [grey50]{escape(str(response_payload))}[/grey50]",
                )
            )
            return response

        except ApiException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)
        finally:
            # Clean up the token after the request is done
            if token in chunk_download_tokens:
                del chunk_download_tokens[token]


@upload_router.get(
    "/_internal/chunks/{token}",
    summary="Internal endpoint for frontends to download chunks",
    include_in_schema=False,
)
async def download_chunk(token: str):
    chunk_path = chunk_download_tokens.pop(token, None)
    if not chunk_path or not chunk_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found or token invalid.")
    response = FileResponse(chunk_path, media_type="application/octet-stream")
    logging.debug(f"Sending file response with status {response.status_code} and headers {response.headers}")
    return response


@router.get("/files", summary="Lists all uploaded files")
async def list_files(
    page_size: int = Query(20, ge=1, le=100),
    page_token: str | None = Query(None),
):
    logging.info(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] " f"[bold]收到文件列表请求[/bold] | 页大小: {page_size}"
    )
    files_response = file_manager.list_files(page_size, page_token)
    logging.info(
        f"[bold yellow]▶[/bold yellow] [dim yellow]后端→调用者[/dim yellow] "
        f"[bold]返回文件列表[/bold] | 数量: {len(files_response.get('files', []))}"
    )
    return files_response


@router.get("/files/{name:path}", summary="Gets metadata for a specific file")
async def get_file(request: Request, name: str):
    logging.info(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] " f"[bold]收到获取文件请求[/bold] | 文件: [green]{name}[/green]"
    )
    # Cache-first approach
    cached_file = file_manager.get_file_metadata(name)
    if cached_file and cached_file.state == "ACTIVE":
        logging.info(
            f"[bold yellow]▶[/bold yellow] [dim yellow]后端→调用者[/dim yellow] "
            f"[bold]返回缓存文件元数据[/bold] | 文件: [green]{name}[/green]"
        )
        return cached_file

    # If not in cache or not active, fetch from a frontend
    request_id = str(uuid.uuid4())
    async with manager.monitored_proxy_request(request_id, request):
        try:
            response_payload = await manager.proxy_request(
                command_type="get_file",
                payload={"file_name": name},
                request=request,
                request_id=request_id,
            )
            file_metadata = File.model_validate(response_payload["file"])
            file_manager.save_file_metadata(file_metadata)  # Update cache
            logging.info(format_response_log("backend_to_caller", request_id, f"返回远程文件元数据 | 文件: [green]{name}[/green]"))
            return file_metadata
        except ApiException as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/files/{name:path}", summary="Deletes a file", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(request: Request, name: str):
    logging.info(
        f"[bold yellow]◀[/bold yellow] [dim yellow]调用者→后端[/dim yellow] " f"[bold]收到删除文件请求[/bold] | 文件: [red]{name}[/red]"
    )
    request_id = str(uuid.uuid4())
    async with manager.monitored_proxy_request(request_id, request):
        try:
            await manager.proxy_request(
                command_type="delete_file",
                payload={"file_name": name},
                request=request,
                request_id=request_id,
            )
            # If successful, remove from our local store
            file_manager.delete_file_metadata(name)
            response = Response(status_code=status.HTTP_204_NO_CONTENT)
            logging.info(
                format_response_log(
                    "backend_to_caller", request_id, f"删除文件成功 | 文件: [red]{name}[/red] | 状态: {response.status_code}"
                )
            )
            return response
        except ApiException as e:
            # If the file is already deleted on Gemini's side, we should also delete it locally.
            if e.status_code == 404:
                file_manager.delete_file_metadata(name)
                response = Response(status_code=status.HTTP_204_NO_CONTENT)
                logging.debug(f"Sending response with status {response.status_code} and headers {response.headers}")
                return response
            raise HTTPException(status_code=e.status_code, detail=e.detail)
