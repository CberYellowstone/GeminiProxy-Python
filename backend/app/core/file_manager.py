"""文件管理模块 (方案 B)

负责管理文件缓存、元数据、后台清理和 sha256 计算。
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional, Set, Tuple
import string

from app.core.config import settings
from app.core.log_utils import Logger
from fastapi import UploadFile

ISO_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T"
    r"(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)

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


@dataclass
class ChunkUploadState:
    temp_path: Path
    sha256: hashlib._hashlib.HASH = field(default_factory=hashlib.sha256)
    size_bytes: int = 0


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
        self.file_cache_dir = Path(settings.FILE_CACHE_DIR).resolve()
        # 确保缓存目录在项目根目录之外，或者在 .gitignore 中，避免触发重载
        # 这里我们假设 settings.FILE_CACHE_DIR 配置正确，或者我们可以在这里强制使用绝对路径
        # 如果它是相对路径，确保它不在被监控的目录中，或者被忽略
        self.file_cache_dir.mkdir(parents=True, exist_ok=True)

        # 核心元数据存储 (sha256 -> FileCacheEntry)
        self.metadata_store: Dict[str, FileCacheEntry] = {}
        # 反向映射 (gemini_file_name -> sha256)
        self.reverse_mapping: Dict[str, str] = {}
        # 临时上传会话 (session_id -> (metadata, created_at))
        self.upload_sessions: Dict[str, Any] = {}
        # 分块上传状态
        self.chunk_upload_states: Dict[str, ChunkUploadState] = {}
        # 记录被显式删除的 sha256，防止异步删除期间被再次引用
        self.deleted_shas: set[str] = set()
        # 记录被删除的文件别名 (files/<id>、裸id 等) -> sha256
        self.deleted_alias_map: Dict[str, str] = {}

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

    async def save_stream_to_cache(
        self, stream: AsyncGenerator[bytes, None], filename: str
    ) -> Tuple[str, Path, int]:
        """
        将任何异步字节流保存到缓存，并同步计算 sha256 和大小。

        Args:
            stream: 任何异步字节生成器。
            filename: 用于创建临时文件的原始文件名。

        Returns:
            一个元组 (sha256_hex, file_path, size_bytes)。
        """
        sha256 = hashlib.sha256()
        size_bytes = 0
        temp_path = self.file_cache_dir / f"temp_{filename}"

        try:
            with open(temp_path, "wb") as f:
                async for chunk in stream:
                    sha256.update(chunk)
                    f.write(chunk)
                    size_bytes += len(chunk)

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
                size=size_bytes,
            )
            return sha256_hex, final_path, size_bytes
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    # ========================================================================
    # 分块上传管理
    # ========================================================================

    def _create_chunk_state(self, session_id: str) -> ChunkUploadState:
        temp_path = self.file_cache_dir / f"chunk_{session_id}"
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        state = ChunkUploadState(temp_path=temp_path)
        self.chunk_upload_states[session_id] = state
        return state

    def append_chunk_data(self, session_id: str, data: bytes, expected_offset: int) -> int:
        state = self.chunk_upload_states.get(session_id)
        if not state:
            state = self._create_chunk_state(session_id)

        if state.size_bytes != expected_offset:
            raise ValueError(f"Offset mismatch: expected {state.size_bytes}, got {expected_offset}")

        with open(state.temp_path, "ab") as f:
            f.write(data)
        state.sha256.update(data)
        state.size_bytes += len(data)
        return state.size_bytes

    def finalize_chunk_upload(self, session_id: str) -> Tuple[str, Path, int]:
        state = self.chunk_upload_states.pop(session_id, None)
        if not state:
            raise ValueError("Chunk upload state not found")

        sha256_hex = state.sha256.hexdigest()
        final_path = self._get_cache_path(sha256_hex)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(state.temp_path, final_path)

        Logger.event(
            "FILE_CACHE_SAVE",
            "文件已保存到缓存",
            sha256=sha256_hex,
            path=str(final_path),
            size=state.size_bytes,
        )
        return sha256_hex, final_path, state.size_bytes

    def discard_chunk_upload(self, session_id: str):
        state = self.chunk_upload_states.pop(session_id, None)
        if state and state.temp_path.exists():
            try:
                state.temp_path.unlink()
            except OSError:
                pass

    # ========================================================================
    # 元数据管理
    # ========================================================================

    def _register_aliases(self, sha256: str, *aliases: str):
        """注册反向映射别名，兼容 files/<id> 及末尾裸 ID"""
        for alias in aliases:
            if not alias:
                continue
            normalized = alias.strip()
            if not normalized:
                continue
            self.reverse_mapping[normalized] = sha256
            Logger.debug("注册文件别名", alias=normalized, sha256=sha256[:8])
            if "/" in normalized:
                tail = normalized.split("/")[-1]
                if tail and tail != normalized:
                    self.reverse_mapping[tail] = sha256
                    Logger.debug("注册文件别名", alias=tail, sha256=sha256[:8])

    def _remove_aliases(self, *aliases: str):
        """移除反向映射别名，同时移除裸 ID 映射"""
        for alias in aliases:
            if not alias:
                continue
            normalized = alias.strip()
            if not normalized:
                continue
            if self.reverse_mapping.pop(normalized, None):
                Logger.debug("移除文件别名", alias=normalized)
            if "/" in normalized:
                tail = normalized.split("/")[-1]
                if tail and tail != normalized and self.reverse_mapping.pop(tail, None):
                    Logger.debug("移除文件别名", alias=tail)

    def extract_sha256_hex(self, remote_file: Dict[str, Any]) -> Optional[str]:
        """从远端文件响应中解析 sha256（支持 base64 或 hex 格式）"""
        sha_candidates = (
            remote_file.get("sha256Hash"),
            remote_file.get("sha256_hash"),
            remote_file.get("sha256"),
        )
        for candidate in sha_candidates:
            if not candidate:
                continue
            candidate = str(candidate).strip()
            if not candidate:
                continue
            if len(candidate) == 64 and all(c in string.hexdigits for c in candidate):
                return candidate.lower()
            try:
                decoded = base64.b64decode(candidate)
                return decoded.hex()
            except Exception:
                Logger.warning("远程 sha256Hash 解析失败", value=candidate, file_name=remote_file.get("name"))
        return None

    def ensure_remote_entry(self, remote_file: Dict[str, Any]) -> Optional[FileCacheEntry]:
        """
        当本地不存在缓存条目时，根据远端 files.get 响应创建一个占位的元数据条目。
        """
        sha256_hex = self.extract_sha256_hex(remote_file)
        if not sha256_hex:
            Logger.warning("远程文件缺少 sha256Hash，无法登记", file_name=remote_file.get("name"))
            return None

        entry = self.metadata_store.get(sha256_hex)
        if entry:
            return entry

        placeholder_path = self.file_cache_dir / "remote_stub" / f"{sha256_hex}.bin"
        placeholder_path.parent.mkdir(parents=True, exist_ok=True)

        size_value = remote_file.get("sizeBytes") or remote_file.get("size_bytes")
        try:
            size_int = int(size_value) if size_value is not None else 0
        except (TypeError, ValueError):
            Logger.warning("远程文件 sizeBytes 无法解析", size=size_value, file_name=remote_file.get("name"))
            size_int = 0

        display_name = remote_file.get("displayName") or remote_file.get("display_name") or remote_file.get("name")
        mime_type = remote_file.get("mimeType") or remote_file.get("mime_type")

        entry = FileCacheEntry(
            sha256=sha256_hex,
            local_path=placeholder_path,
            original_filename=display_name or sha256_hex,
            mime_type=mime_type,
            size_bytes=size_int,
        )

        expiration_raw = remote_file.get("expirationTime") or remote_file.get("expiration_time")
        if expiration_raw:
            parsed = self._parse_iso_timestamp(expiration_raw)
            if parsed:
                entry.gemini_file_expiration = parsed

        self.metadata_store[sha256_hex] = entry
        Logger.event(
            "METADATA_REMOTE",
            "创建远程文件元数据占位",
            sha256=sha256_hex[:8],
            file_name=remote_file.get("name"),
        )
        return entry

    def _parse_iso_timestamp(self, value: Optional[str]) -> Optional[datetime]:
        """兼容 Google 返回的纳秒时间戳，转换为 Python datetime"""
        if not value:
            return None

        match = ISO_TIMESTAMP_RE.match(value.strip())
        if not match:
            Logger.warning("无法解析时间戳", timestamp=value)
            return None

        base = f"{match.group('date')}T{match.group('time')}"
        frac = match.group('frac')
        if frac:
            frac = (frac + "000000")[:6]  # Python datetime 仅支持微秒
            base = f"{base}.{frac}"

        tz = match.group('tz') or "+00:00"
        if tz == "Z":
            tz = "+00:00"

        try:
            return datetime.fromisoformat(base + tz)
        except ValueError as exc:
            Logger.warning("时间戳解析失败", timestamp=value, exc=exc)
            return None

    def get_metadata_entry(self, sha256: str) -> Optional[FileCacheEntry]:
        """通过 sha256 获取元数据条目，并更新访问时间"""
        entry = self.metadata_store.get(sha256)
        if entry:
            entry.last_accessed_at = datetime.now(timezone.utc)
        return entry

    def get_sha256_by_filename(self, file_name: str) -> Optional[str]:
        """通过 gemini file name 或冗余 fileUri 获取 sha256"""
        if not file_name:
            return None

        mapped = self.reverse_mapping.get(file_name)
        if mapped:
            Logger.debug("命中文件别名", alias=file_name, sha256=mapped[:8])
            return mapped

        # 处理完整 URL，例如 https://.../files/<id>
        if "files/" in file_name:
            suffix = file_name[file_name.index("files/") :]
            mapped = self.reverse_mapping.get(suffix)
            if mapped:
                Logger.debug("命中文件别名", alias=suffix, sha256=mapped[:8])
                return mapped

        # 兼容 fileUri 直接携带 sha256 的情况 (如 files/<sha256>)
        candidate = file_name.split('/')[-1]
        if len(candidate) == 64 and all(c in string.hexdigits for c in candidate):
            if candidate in self.metadata_store:
                Logger.debug("命中裸 sha256", alias=file_name, sha256=candidate[:8])
                return candidate

        if file_name.startswith("files/"):
            Logger.debug("文件别名未找到", alias=file_name)

        # fallback: 扫描 replication_map，防止别名映射缺失
        normalized = file_name.strip()
        fallback_candidates = {normalized}
        if "files/" in normalized:
            fallback_candidates.add(normalized.split("files/", 1)[-1])
        else:
            fallback_candidates.add(f"files/{normalized}")

        for sha, entry in self.metadata_store.items():
            for data in entry.replication_map.values():
                remote_name = data.get("name")
                if remote_name and remote_name in fallback_candidates:
                    Logger.debug("通过 replication_map 找到文件", alias=file_name, sha256=sha[:8])
                    self._register_aliases(sha, remote_name)
                    return sha
                uri = data.get("uri")
                if uri and "files/" in uri:
                    uri_tail = uri.split("files/", 1)[-1]
                    if uri_tail and (uri_tail in fallback_candidates):
                        Logger.debug("通过 uri 找到文件", alias=file_name, sha256=sha[:8])
                        self._register_aliases(sha, uri, uri_tail)
                        return sha

        return None

    def create_metadata_entry(
        self, *, sha256: str, file_path: Path, filename: str, mime_type: Optional[str], size_bytes: int
    ) -> FileCacheEntry:
        """创建一个新的元数据条目"""
        entry = FileCacheEntry(
            sha256=sha256,
            local_path=file_path,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
        )
        self.metadata_store[sha256] = entry
        # 注册本地 fallback fileUri，便于在复制前使用
        short_sha = sha256[:32]
        self._register_aliases(
            sha256,
            sha256,
            short_sha,
            f"files/{sha256}",
            f"files/{short_sha}",
        )
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
                self._register_aliases(sha256, file_name)
            uri_value = gemini_file.get("uri")
            if uri_value:
                replication_data["uri"] = uri_value
            # 如果这是第一次成功上传，记录过期时间
            if not entry.gemini_file_expiration:
                expiration_time = gemini_file.get("expirationTime")
                if expiration_time:
                    parsed_expiration = self._parse_iso_timestamp(expiration_time)
                    if parsed_expiration:
                        entry.gemini_file_expiration = parsed_expiration

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
        short_sha = sha256[:32]
        self._remove_aliases(sha256, short_sha, f"files/{sha256}", f"files/{short_sha}")
        for client_id, data in entry.replication_map.items():
            if "name" in data:
                self._remove_aliases(data["name"])

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

    # ========================================================================
    # 删除标记管理
    # ========================================================================

    def _normalize_aliases_for_tombstone(self, alias: Optional[str]) -> Set[str]:
        """生成一组可用于 tombstone 的别名形式"""
        if not alias:
            return set()
        normalized_aliases: Set[str] = set()
        token = alias.strip()
        if not token:
            return normalized_aliases

        def _add(value: str):
            value = value.strip()
            if value:
                normalized_aliases.add(value)

        _add(token)
        if "files/" in token:
            tail = token.split("files/", 1)[-1]
            if tail and tail != token:
                _add(tail)
                _add(f"files/{tail}")
        else:
            _add(f"files/{token}")

        return normalized_aliases

    def mark_deleted(self, sha256: Optional[str], aliases: Optional[Set[str]] = None):
        """记录一个 sha256 被显式删除，并记住相关别名"""
        if not sha256:
            return
        self.deleted_shas.add(sha256)
        tombstone_aliases: Set[str] = set()
        tombstone_aliases.update(self._normalize_aliases_for_tombstone(sha256))
        tombstone_aliases.update(self._normalize_aliases_for_tombstone(f"files/{sha256}"))
        if aliases:
            for alias in aliases:
                tombstone_aliases.update(self._normalize_aliases_for_tombstone(alias))
        for alias in tombstone_aliases:
            self.deleted_alias_map[alias] = sha256
        Logger.debug(
            "标记文件为已删除",
            sha256=sha256[:8],
            aliases=list(sorted(tombstone_aliases))[:3],
        )

    def clear_deleted_flag(self, sha256: Optional[str]):
        """清除显式删除标记"""
        if not sha256:
            return
        if sha256 in self.deleted_shas:
            self.deleted_shas.discard(sha256)
        aliases_to_remove = [alias for alias, value in self.deleted_alias_map.items() if value == sha256]
        for alias in aliases_to_remove:
            self.deleted_alias_map.pop(alias, None)
        if aliases_to_remove:
            Logger.debug("清除已删除标记", sha256=sha256[:8], aliases=aliases_to_remove[:3])

    def is_marked_deleted(self, sha256: Optional[str]) -> bool:
        """判断一个 sha256 是否仍处于显式删除状态"""
        return bool(sha256 and sha256 in self.deleted_shas)

    def is_name_marked_deleted(self, name: Optional[str]) -> bool:
        """判断一个文件名/URI 是否被标记为已删除"""
        if not name:
            return False
        aliases = self._normalize_aliases_for_tombstone(name)
        return any(alias in self.deleted_alias_map for alias in aliases)

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


            # 3. 清理过期的上传会话
            expired_sessions = []
            session_timeout = timedelta(hours=1)  # 1小时超时
            for session_id, session_data in list(self.upload_sessions.items()):
                # session_data 可能是旧的格式(直接是metadata)或新的格式(metadata, created_at)
                if isinstance(session_data, tuple) and len(session_data) == 2:
                    metadata, created_at = session_data
                    created_at = created_at.replace(tzinfo=timezone.utc)
                    if now - created_at > session_timeout:
                        expired_sessions.append(session_id)
                else:
                    # 旧格式，无法判断时间，直接清理超过1天的
                    expired_sessions.append(session_id)

            if expired_sessions:
                Logger.info(f"清理 {len(expired_sessions)} 个过期的上传会话...")
                for session_id in expired_sessions:
                    self.upload_sessions.pop(session_id, None)

            # 4. 执行删除
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
