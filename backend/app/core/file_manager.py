"""文件管理模块 (方案 B)

负责管理文件缓存、元数据、后台清理和 sha256 计算。
"""

import asyncio
import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.core.config import settings
from app.core.log_utils import Logger
from fastapi import UploadFile

# ============================================================================
# 数据类 (方案 B)
# ============================================================================


@dataclass
class FileCacheEntry:
    """文件缓存元数据条目"""

    sha256: str
    local_path: Path
    original_filename: str
    mime_type: Optional[str]
    size_bytes: int
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    gemini_file_expiration: Optional[datetime] = None
    replication_map: Dict[str, Dict[str, Any]] = field(default_factory=dict)


# ============================================================================
# 文件管理器 (方案 B)
# ============================================================================


class FileManager:
    """文件管理器

    职责:
    1.  将上传的文件内容存储到本地缓存。
    2.  计算文件的 sha256 作为唯一标识。
    3.  管理文件的核心元数据（包括复制状态）。
    4.  提供后台任务进行缓存清理 (TTL + LRU)。
    """

    def __init__(self):
        """初始化文件管理器"""
        # 文件缓存目录
        self.file_cache_dir = Path(settings.FILE_CACHE_DIR)
        self.file_cache_dir.mkdir(parents=True, exist_ok=True)

        # 核心元数据存储 (sha256 -> FileCacheEntry)
        self.metadata_store: Dict[str, FileCacheEntry] = {}
        # 反向映射 (gemini_file_name -> sha256)
        self.reverse_mapping: Dict[str, str] = {}

        Logger.event("INIT", "文件管理器(方案 B)初始化", cache_dir=str(self.file_cache_dir))

    def _get_cache_path(self, sha256: str) -> Path:
        """根据 sha256 生成分层的文件缓存路径"""
        # 使用前4个字符创建两级子目录，避免单个目录下文件过多
        # 例如: d29a...f2 -> /.../file_cache/d2/9a/d29a...f2.bin
        if len(sha256) < 4:
            raise ValueError("sha256 ahash must be at least 4 characters long")
        sub_dir1 = sha256[:2]
        sub_dir2 = sha256[2:4]
        return self.file_cache_dir / sub_dir1 / sub_dir2 / f"{sha256}.bin"

    async def save_file_to_cache(self, file: UploadFile) -> Tuple[str, Path]:
        """
        将上传的文件流保存到缓存目录，并同步计算 sha256。

        Args:
            file: FastAPI 的 UploadFile 对象，包含文件流。

        Returns:
            一个元组 (sha256_hex, file_path)，包含计算出的 sha256 和文件保存的路径。
        """
        sha256 = hashlib.sha256()
        # 先保存到一个临时位置，计算完 sha256 后再移动到最终位置
        temp_path = self.file_cache_dir / f"temp_{file.filename}"

        try:
            with open(temp_path, "wb") as f:
                # 逐块读取，以处理大文件并计算哈希
                while chunk := await file.read(8192):  # 8KB chunks
                    sha256.update(chunk)
                    f.write(chunk)

            sha256_hex = sha256.hexdigest()
            final_path = self._get_cache_path(sha256_hex)

            # 创建目标子目录
            final_path.parent.mkdir(parents=True, exist_ok=True)

            # 将临时文件移动到最终位置
            shutil.move(temp_path, final_path)

            Logger.event(
                "FILE_CACHE_SAVE",
                "文件已保存到缓存",
                sha256=sha256_hex,
                path=str(final_path),
            )
            return sha256_hex, final_path
        finally:
            # 确保临时文件在任何情况下都被删除
            if os.path.exists(temp_path):
                os.remove(temp_path)
            # 确保文件指针回到开头，以便后续可能的操作
            await file.seek(0)

    # ========================================================================
    # 元数据管理
    # ========================================================================

    def get_metadata_entry(self, sha256: str) -> Optional[FileCacheEntry]:
        """通过 sha256 获取元数据条目，并更新访问时间"""
        entry = self.metadata_store.get(sha256)
        if entry:
            entry.last_accessed_at = datetime.now(timezone.utc)
        return entry

    def get_sha256_by_filename(self, file_name: str) -> Optional[str]:
        """通过 gemini file name 获取 sha256"""
        return self.reverse_mapping.get(file_name)

    def create_metadata_entry(self, sha256: str, file_path: Path, file: UploadFile) -> FileCacheEntry:
        """创建一个新的元数据条目"""
        entry = FileCacheEntry(
            sha256=sha256,
            local_path=file_path,
            original_filename=file.filename,
            mime_type=file.content_type,
            size_bytes=file.size,
        )
        self.metadata_store[sha256] = entry
        Logger.event("METADATA_CREATE", "创建文件元数据", sha256=sha256)
        return entry

    def update_replication_status(
        self, sha256: str, client_id: str, status: str, gemini_file: Optional[Dict] = None
    ):
        """更新文件的复制状态"""
        entry = self.get_metadata_entry(sha256)
        if not entry:
            return

        replication_data = {"status": status}
        if gemini_file:
            replication_data.update(gemini_file)
            file_name = gemini_file.get("name")
            if file_name:
                # 更新反向映射
                self.reverse_mapping[file_name] = sha256
                # 如果这是第一次成功上传，记录过期时间
                if not entry.gemini_file_expiration and "expirationTime" in gemini_file:
                    entry.gemini_file_expiration = datetime.fromisoformat(gemini_file["expirationTime"])

        entry.replication_map[client_id] = replication_data
        Logger.debug(
            "更新复制状态",
            sha256=sha256,
            client_id=client_id,
            status=status,
        )

    def reset_replication_map(self, sha256: str):
        """全局重置：清空文件的复制地图"""
        entry = self.get_metadata_entry(sha256)
        if not entry:
            return

        # 从反向映射中删除所有相关的旧 file_name
        for client_id, data in entry.replication_map.items():
            if "name" in data:
                self.reverse_mapping.pop(data["name"], None)

        entry.replication_map.clear()
        entry.gemini_file_expiration = None  # 重置过期时间
        Logger.event("REPLICATION_RESET", "文件复制地图已重置", sha256=sha256)

    def _delete_entry(self, sha256: str):
        """内部方法：删除一个缓存条目及其关联的所有数据"""
        entry = self.metadata_store.pop(sha256, None)
        if not entry:
            return

        # 从反向映射中删除
        for client_id, data in entry.replication_map.items():
            if "name" in data:
                self.reverse_mapping.pop(data["name"], None)

        # 删除物理文件
        try:
            if entry.local_path.exists():
                os.remove(entry.local_path)
                # 尝试删除空的父目录
                try:
                    entry.local_path.parent.rmdir()
                    entry.local_path.parent.parent.rmdir()
                except OSError:
                    # 目录非空，忽略错误
                    pass
        except OSError as e:
            Logger.error("删除缓存文件失败", exc=e, path=str(entry.local_path))

        Logger.event("FILE_CACHE_DELETE", "文件已从缓存中删除", sha256=sha256)

    async def periodic_cleanup_task(self):
        """后台定期清理任务，结合 TTL 和 LRU 策略。"""
        while True:
            await asyncio.sleep(settings.FILE_CACHE_CLEANUP_INTERVAL)
            Logger.info("开始执行文件缓存清理任务...")

            now = datetime.now(timezone.utc)
            to_delete = set()

            # 1. TTL 清理：标记所有已过期的文件
            for sha256, entry in self.metadata_store.items():
                if entry.gemini_file_expiration and now > entry.gemini_file_expiration:
                    to_delete.add(sha256)

            if to_delete:
                Logger.info(f"TTL清理: 发现 {len(to_delete)} 个过期文件。")

            # 2. LRU 清理：如果超出配额，继续标记最久未使用的文件
            try:
                total_size_bytes = sum(
                    entry.size_bytes for sha256, entry in self.metadata_store.items() if sha256 not in to_delete
                )
                quota_bytes = settings.FILE_CACHE_QUOTA_MB * 1024 * 1024

                if total_size_bytes > quota_bytes:
                    Logger.info(
                        f"LRU清理: 缓存超出配额 ({(total_size_bytes / 1024 / 1024):.2f}MB > {settings.FILE_CACHE_QUOTA_MB}MB)。"
                    )
                    # 按最后访问时间升序排序 (最旧的在前)
                    sorted_entries = sorted(
                        [entry for sha256, entry in self.metadata_store.items() if sha256 not in to_delete],
                        key=lambda x: x.last_accessed_at,
                    )

                    for entry in sorted_entries:
                        if total_size_bytes <= quota_bytes:
                            break
                        to_delete.add(entry.sha256)
                        total_size_bytes -= entry.size_bytes
            except Exception as e:
                Logger.error("计算缓存大小时发生错误", exc=e)


            # 3. 执行删除
            if to_delete:
                Logger.info(f"准备删除 {len(to_delete)} 个缓存条目...")
                for sha256 in list(to_delete):
                    self._delete_entry(sha256)
                Logger.info("缓存清理任务完成。")
            else:
                Logger.info("缓存状态正常，无需清理。")

    def cleanup_all_cache_files(self):
        """
        删除整个文件缓存目录。
        在应用关闭时调用，用于清理。
        """
        try:
            if self.file_cache_dir.exists():
                shutil.rmtree(self.file_cache_dir)
                Logger.event("SHUTDOWN_CLEANUP", "删除文件缓存目录", cache_dir=str(self.file_cache_dir))
        except OSError as e:
            Logger.error("删除文件缓存目录失败", exc=e, cache_dir=str(self.file_cache_dir))


# ============================================================================
# 全局文件管理器实例
# ============================================================================

file_manager = FileManager()
