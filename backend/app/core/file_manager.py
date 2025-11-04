"""文件管理模块

负责管理文件上传会话、文件元数据缓存和临时文件清理。
"""

import asyncio
import json
import logging
import re
import secrets
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.gemini_files import File as FileMetadata

# ============================================================================
# 数据类
# ============================================================================


@dataclass
class UploadSession:
    """上传会话数据类

    Attributes:
        real_upload_url: 真实的 Gemini 上传 URL
        metadata: 文件元数据
        created_at: 会话创建时间
        temp_chunks: 临时文件块路径列表
    """

    real_upload_url: str
    metadata: dict[str, Any]
    created_at: datetime
    temp_chunks: list[Path] = field(default_factory=list)


# ============================================================================
# 文件管理器
# ============================================================================


class FileManager:
    """文件管理器

    职责:
    1. 管理上传会话的生命周期
    2. 处理文件块的上传和下载
    3. 管理文件元数据缓存
    4. 定期清理过期资源
    """

    # ========================================================================
    # 初始化
    # ========================================================================

    def __init__(self):
        """初始化文件管理器"""
        # 文件元数据缓存（单一真相来源）
        self.file_metadata_store: dict[str, FileMetadata] = {}

        # 上传会话管理
        self.upload_sessions: dict[str, UploadSession] = {}

        # 一次性下载令牌存储：用于前端下载临时文件块
        self.chunk_download_tokens: dict[str, Path] = {}

        # 临时文件块存储目录
        self.temp_chunks_dir = Path(settings.TEMP_CHUNKS_DIR)
        self.temp_chunks_dir.mkdir(parents=True, exist_ok=True)

        logging.info(f"Temporary chunk directory set to: {self.temp_chunks_dir}")

    # ========================================================================
    # 上传会话管理
    # ========================================================================

    def create_upload_session(self, real_upload_url: str, metadata: dict) -> str:
        """创建新的上传会话

        Args:
            real_upload_url: 真实的 Gemini 上传 URL
            metadata: 文件元数据

        Returns:
            代理会话 ID
        """
        proxy_session_id = str(uuid.uuid4())
        self.upload_sessions[proxy_session_id] = UploadSession(
            real_upload_url=real_upload_url,
            metadata=metadata,
            created_at=datetime.now(),
        )

        display_name = metadata.get("file", {}).get("displayName", "Unknown")
        logging.info(f"Created upload session {proxy_session_id} for {display_name}")

        return proxy_session_id

    def get_upload_session(self, proxy_session_id: str) -> UploadSession | None:
        """通过代理会话 ID 获取上传会话

        Args:
            proxy_session_id: 代理会话 ID

        Returns:
            上传会话对象，不存在则返回 None
        """
        return self.upload_sessions.get(proxy_session_id)

    # ========================================================================
    # 上传数据处理
    # ========================================================================

    @staticmethod
    def extract_upload_offset(request) -> int:
        """从请求头中提取上传偏移量

        优先级: Content-Range > X-Goog-Upload-Offset

        Args:
            request: FastAPI 请求对象

        Returns:
            上传偏移量（字节）

        Raises:
            ValueError: 无法解析偏移量时抛出
        """
        content_range_header = request.headers.get("Content-Range")
        x_goog_upload_offset_header = request.headers.get("X-Goog-Upload-Offset")

        # 尝试从 Content-Range 解析 (格式: "bytes 100-200/500")
        if content_range_header:
            match = re.search(r"bytes (\d+)-", content_range_header)
            if match:
                return int(match.group(1))

        # 尝试从 X-Goog-Upload-Offset 解析
        if x_goog_upload_offset_header is not None:
            try:
                return int(x_goog_upload_offset_header)
            except (ValueError, TypeError):
                raise ValueError("Invalid X-Goog-Upload-Offset header.")

        # 两者都不存在
        raise ValueError("Missing upload offset information (Content-Range or X-Goog-Upload-Offset).")

    async def save_chunk_to_temp_file(self, proxy_session_id: str, request) -> Path:
        """保存数据块到临时文件

        Args:
            proxy_session_id: 代理会话 ID
            request: FastAPI 请求对象（包含流式数据）

        Returns:
            临时文件路径

        Raises:
            ValueError: 会话不存在
            IOError: 文件写入失败
        """
        session = self.get_upload_session(proxy_session_id)
        if not session:
            raise ValueError(f"Upload session {proxy_session_id} not found")

        # 生成临时文件
        chunk_id = str(uuid.uuid4())
        chunk_path = self.temp_chunks_dir / f"chunk_{chunk_id}.bin"
        session.temp_chunks.append(chunk_path)

        # 保存数据流
        try:
            with open(chunk_path, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
            return chunk_path
        except Exception as e:
            logging.error(f"Failed to write chunk to temp file: {e}")
            # 清理失败的文件
            if chunk_path.exists():
                chunk_path.unlink()
            raise IOError(f"Failed to save file chunk: {str(e)}")

    def process_upload_response(self, proxy_session_id: str, response_payload: dict[str, Any]) -> dict[str, Any]:
        """处理上传响应并更新元数据

        Args:
            proxy_session_id: 代理会话 ID
            response_payload: 前端返回的响应数据

        Returns:
            处理后的响应数据（包含 status, headers, content, is_final）
            content 已序列化为字符串，可直接用于 HTTP 响应
        """
        response_status = response_payload.get("status", 200)
        response_headers = response_payload.get("headers", {})
        response_body = response_payload.get("body", {})

        # 检查是否为最终块（包含文件元数据）
        is_final_chunk = isinstance(response_body, dict) and "file" in response_body

        if is_final_chunk:
            # 保存文件元数据
            file_metadata = FileMetadata.model_validate(response_body["file"])
            self.save_file_metadata(file_metadata)

            # 清理会话
            self.cleanup_session(proxy_session_id)

            logging.info(f"Upload completed for file: {file_metadata.name}")

        # 序列化响应内容
        content = json.dumps(response_body) if isinstance(response_body, dict) else str(response_body)

        return {"status": response_status, "headers": response_headers, "content": content, "is_final": is_final_chunk}

    # ========================================================================
    # 临时文件块令牌管理
    # ========================================================================

    def generate_chunk_download_token(self, chunk_path: Path) -> str:
        """生成一次性下载令牌

        Args:
            chunk_path: 临时文件块路径

        Returns:
            安全的 URL-safe 令牌字符串
        """
        token = secrets.token_urlsafe(32)
        self.chunk_download_tokens[token] = chunk_path
        return token

    def consume_chunk_download_token(self, token: str) -> Path | None:
        """消耗一次性下载令牌（使用后失效）

        Args:
            token: 下载令牌

        Returns:
            文件块路径，如果令牌无效返回 None
        """
        return self.chunk_download_tokens.pop(token, None)

    def invalidate_chunk_download_token(self, token: str):
        """失效一个下载令牌

        Args:
            token: 要失效的令牌
        """
        self.chunk_download_tokens.pop(token, None)

    # ========================================================================
    # 文件元数据管理
    # ========================================================================

    def save_file_metadata(self, file: FileMetadata):
        """保存文件元数据到缓存

        Args:
            file: 文件元数据对象
        """
        self.file_metadata_store[file.name] = file
        logging.info(f"Saved metadata for file: {file.name}")

    def get_file_metadata(self, file_name: str) -> FileMetadata | None:
        """从缓存获取文件元数据

        Args:
            file_name: 文件名称（如 files/abc123 或 abc123）

        Returns:
            文件元数据对象，不存在则返回 None
        """
        # 确保文件名包含 files/ 前缀
        if not file_name.startswith("files/"):
            file_name = f"files/{file_name}"
        return self.file_metadata_store.get(file_name)

    def list_files(self, page_size: int, page_token: str | None) -> dict:
        """列出所有文件（带分页）

        Args:
            page_size: 每页文件数量
            page_token: 分页令牌（起始索引）

        Returns:
            包含文件列表和下一页令牌的字典
        """
        # 按创建时间倒序排序
        all_files = sorted(self.file_metadata_store.values(), key=lambda f: f.create_time, reverse=True)

        # 解析分页令牌
        start_index = 0
        if page_token:
            try:
                start_index = int(page_token)
            except ValueError:
                pass  # 无效令牌，从头开始

        # 分页切片
        end_index = start_index + page_size
        paginated_files = all_files[start_index:end_index]

        # 生成下一页令牌
        next_page_token = str(end_index) if end_index < len(all_files) else None

        return {
            "files": paginated_files,
            "nextPageToken": next_page_token,
        }

    def delete_file_metadata(self, file_name: str) -> bool:
        """从缓存删除文件元数据

        Args:
            file_name: 文件名称（如 files/abc123 或 abc123）

        Returns:
            是否成功删除
        """
        # 确保文件名包含 files/ 前缀
        if not file_name.startswith("files/"):
            file_name = f"files/{file_name}"

        if file_name in self.file_metadata_store:
            del self.file_metadata_store[file_name]
            logging.info(f"Deleted metadata for file: {file_name}")
            return True
        return False

    # ========================================================================
    # 清理与维护
    # ========================================================================

    def cleanup_session(self, proxy_session_id: str):
        """清理上传会话及其关联的临时文件

        Args:
            proxy_session_id: 代理会话 ID
        """
        session = self.upload_sessions.pop(proxy_session_id, None)
        if session:
            # 删除所有临时文件块
            for chunk_path in session.temp_chunks:
                try:
                    if chunk_path.exists():
                        chunk_path.unlink()
                except OSError as e:
                    logging.error(f"Error deleting temp chunk {chunk_path}: {e}")

            logging.info(f"Cleaned up session {proxy_session_id}")

    async def periodic_cleanup_task(self):
        """定期清理过期的上传会话

        在后台运行的异步任务，定期检查并清理超时会话。
        """
        while True:
            await asyncio.sleep(settings.SESSION_CLEANUP_INTERVAL)

            now = datetime.now()
            expiration_threshold = timedelta(seconds=settings.SESSION_EXPIRATION_TIME)

            # 查找过期会话
            expired_sessions = [
                session_id for session_id, session in self.upload_sessions.items() if now - session.created_at > expiration_threshold
            ]

            if expired_sessions:
                logging.info(f"Found {len(expired_sessions)} expired sessions to clean up.")
                for session_id in expired_sessions:
                    self.cleanup_session(session_id)

    def cleanup_all_temp_files(self):
        """删除整个临时目录

        在应用关闭时调用，清理所有临时文件。
        """
        try:
            if self.temp_chunks_dir.exists():
                shutil.rmtree(self.temp_chunks_dir)
                logging.info(f"Successfully removed temporary directory: {self.temp_chunks_dir}")
        except OSError as e:
            logging.error(f"Error removing temporary directory {self.temp_chunks_dir}: {e}")


# ============================================================================
# 全局文件管理器实例
# ============================================================================

file_manager = FileManager()
