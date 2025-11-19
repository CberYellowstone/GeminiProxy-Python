import mimetypes
import os
import zipfile
from pathlib import Path
from typing import Optional

class MimeUtils:
    """MIME 类型处理工具类"""

    # 常见的文件扩展名到 MIME 类型的映射
    EXTENSION_MIME_MAP = {
        # 图片
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.svg': 'image/svg+xml',

        # 文档
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.ms-excel',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.txt': 'text/plain',
        '.rtf': 'application/rtf',

        # 音频
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.m4a': 'audio/mp4',
        '.flac': 'audio/flac',

        # 视频
        '.mp4': 'video/mp4',
        '.avi': 'video/x-msvideo',
        '.mov': 'video/quicktime',
        '.wmv': 'video/x-ms-wmv',
        '.flv': 'video/x-flv',
        '.webm': 'video/webm',
        '.mkv': 'video/x-matroska',

        # 代码和文本
        '.js': 'text/javascript',
        '.css': 'text/css',
        '.html': 'text/html',
        '.htm': 'text/html',
        '.json': 'application/json',
        '.xml': 'text/xml',
        '.csv': 'text/csv',
        '.md': 'text/markdown',
        '.py': 'text/x-python',
        '.java': 'text/x-java-source',
        '.cpp': 'text/x-c++src',
        '.c': 'text/x-csrc',

        # 压缩文件
        '.zip': 'application/zip',
        '.rar': 'application/x-rar-compressed',
        '.tar': 'application/x-tar',
        '.gz': 'application/gzip',
        '.7z': 'application/x-7z-compressed',
    }

    MAGIC_SIGNATURES = [
        (b"%PDF-", "application/pdf", ".pdf"),
        (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
        (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
        (b"GIF87a", "image/gif", ".gif"),
        (b"GIF89a", "image/gif", ".gif"),
        (b"PK\x03\x04", "application/zip", ".zip"),
        (b"PK\x05\x06", "application/zip", ".zip"),
        (b"PK\x07\x08", "application/zip", ".zip"),
        (b"\x1f\x8b\x08", "application/gzip", ".gz"),
        (b"Rar!\x1a\x07\x00", "application/x-rar-compressed", ".rar"),
        (b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed", ".7z"),
        (b"OggS", "application/ogg", ".ogg"),
        (b"ID3", "audio/mpeg", ".mp3"),
        (b"\x00\x00\x00\x18ftyp", "video/mp4", ".mp4"),
        (b"\x1a\x45\xdf\xa3", "video/webm", ".webm"),
    ]

    @classmethod
    def infer_mime_type(cls, filename: str, fallback_mime: str = "application/octet-stream") -> str:
        """
        根据文件名智能推断 MIME 类型

        Args:
            filename: 文件名或路径
            fallback_mime: 无法推断时的默认 MIME 类型

        Returns:
            推断的 MIME 类型
        """
        if not filename:
            return fallback_mime

        # 获取文件扩展名（转换为小写）
        _, ext = os.path.splitext(filename.lower())

        # 首先检查我们的自定义映射
        if ext in cls.EXTENSION_MIME_MAP:
            return cls.EXTENSION_MIME_MAP[ext]

        # 然后尝试使用 mimetypes 库
        guessed_mime, _ = mimetypes.guess_type(filename)
        if guessed_mime:
            return guessed_mime

        # 最后返回默认值
        return fallback_mime

    @classmethod
    def should_correct_mime_type(cls, mime_type: str, filename: str) -> bool:
        """
        判断是否需要修正 MIME 类型

        Args:
            mime_type: 当前的 MIME 类型
            filename: 文件名

        Returns:
            是否需要修正
        """
        if not mime_type or mime_type == "application/octet-stream":
            return True

        # 对于常见的二进制文件类型，如果被标记为 text/plain，也应该修正
        binary_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.pdf',
                           '.mp3', '.wav', '.mp4', '.avi', '.mov', '.zip', '.rar',
                           '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx'}

        _, ext = os.path.splitext(filename.lower())
        if ext in binary_extensions and mime_type.startswith('text/'):
            return True

        return False

    @classmethod
    def get_corrected_mime_type(cls, current_mime: str, filename: str) -> str:
        """
        获取修正后的 MIME 类型

        Args:
            current_mime: 当前的 MIME 类型
            filename: 文件名

        Returns:
            修正后的 MIME 类型
        """
        if not cls.should_correct_mime_type(current_mime, filename):
            return current_mime

        corrected_mime = cls.infer_mime_type(filename)

        # 如果推断出的类型仍然是不常见的未知类型，且原类型不是 application/octet-stream，保持原类型
        unknown_mime_patterns = ["chemical/", "application/x-"]
        is_unknown = any(corrected_mime.startswith(pattern) for pattern in unknown_mime_patterns)

        if is_unknown and current_mime != "application/octet-stream":
            return current_mime

        return corrected_mime

    @classmethod
    def is_text_file(cls, mime_type: str) -> bool:
        """
        判断是否为文本文件

        Args:
            mime_type: MIME 类型

        Returns:
            是否为文本文件
        """
        return mime_type.startswith('text/') or mime_type in [
            'application/json',
            'application/xml',
            'application/javascript',
            'application/x-javascript',
            'text/markdown'
        ]

    @classmethod
    def is_image_file(cls, mime_type: str) -> bool:
        """
        判断是否为图片文件

        Args:
            mime_type: MIME 类型

        Returns:
            是否为图片文件
        """
        return mime_type.startswith('image/')

    @classmethod
    def is_audio_file(cls, mime_type: str) -> bool:
        """
        判断是否为音频文件

        Args:
            mime_type: MIME 类型

        Returns:
            是否为音频文件
        """
        return mime_type.startswith('audio/')

    @classmethod
    def is_video_file(cls, mime_type: str) -> bool:
        """
        判断是否为视频文件

        Args:
            mime_type: MIME 类型

        Returns:
            是否为视频文件
        """
        return mime_type.startswith('video/')

    @classmethod
    def detect_mime_type_from_content(cls, file_path: Path, sample_size: int = 8192) -> Optional[str]:
        """
        根据文件内容检测 MIME 类型（基于常见魔数 + 文本启发）
        """
        try:
            with open(file_path, "rb") as fp:
                sample = fp.read(sample_size)
        except OSError:
            return None

        if not sample:
            return None

        for signature, mime, _ in cls.MAGIC_SIGNATURES:
            if sample.startswith(signature):
                # 针对 Office OpenXML 文档进一步细分
                if mime == "application/zip":
                    detected_office = cls._detect_office_type(file_path)
                    if detected_office:
                        return detected_office
                return mime

        if cls._looks_like_text(sample):
            return "text/plain"

        return None

    @classmethod
    def _detect_office_type(cls, file_path: Path) -> Optional[str]:
        """尝试识别基于 ZIP 容器的 Office 文件"""
        try:
            with zipfile.ZipFile(file_path) as archive:
                names = archive.namelist()
        except (OSError, zipfile.BadZipFile):
            return None

        if any(name.startswith("word/") for name in names):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if any(name.startswith("ppt/") for name in names):
            return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        if any(name.startswith("xl/") for name in names):
            return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return "application/zip"

    @staticmethod
    def _looks_like_text(sample: bytes) -> bool:
        if not sample:
            return False
        text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(32, 127)))
        nontext = sum(byte not in text_chars for byte in sample)
        return nontext / len(sample) < 0.1

    @classmethod
    def guess_extension_from_mime(cls, mime_type: Optional[str], default: str = ".bin") -> str:
        if not mime_type:
            return default

        for ext, mapped in cls.EXTENSION_MIME_MAP.items():
            if mapped == mime_type:
                return ext

        guessed = mimetypes.guess_extension(mime_type)
        if guessed:
            return guessed

        fallback_map = {
            "text/plain": ".txt",
            "application/json": ".json",
            "application/xml": ".xml",
            "application/octet-stream": ".bin",
        }
        return fallback_map.get(mime_type, default)

    @staticmethod
    def normalize_filename(filename: Optional[str]) -> Optional[str]:
        if not filename:
            return None
        cleaned = Path(filename).name.strip()
        return cleaned or None

    @classmethod
    def build_fallback_filename(cls, sha256: str, mime_type: Optional[str] = None) -> str:
        short_sha = (sha256 or "file")[:8]
        extension = cls.guess_extension_from_mime(mime_type, default=".bin")
        return f"file_{short_sha}{extension}"
