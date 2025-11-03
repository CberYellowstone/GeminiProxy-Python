import asyncio
import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.gemini_files import File as FileMetadata


@dataclass
class UploadSession:
    real_upload_url: str
    metadata: Dict[str, Any]
    created_at: datetime
    temp_chunks: List[Path] = field(default_factory=list)


class FileManager:
    def __init__(self):
        self.file_metadata_store: Dict[str, FileMetadata] = {}
        self.upload_sessions: Dict[str, UploadSession] = {}
        self.temp_chunks_dir = Path(settings.TEMP_CHUNKS_DIR)
        self.temp_chunks_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Temporary chunk directory set to: {self.temp_chunks_dir}")

    def create_upload_session(self, real_upload_url: str, metadata: dict) -> str:
        """Creates a new upload session and returns the proxy session ID."""
        proxy_session_id = str(uuid.uuid4())
        self.upload_sessions[proxy_session_id] = UploadSession(
            real_upload_url=real_upload_url,
            metadata=metadata,
            created_at=datetime.now(),
        )
        logging.info(f"Created upload session {proxy_session_id} for {metadata.get('file', {}).get('displayName')}")
        return proxy_session_id

    def get_upload_session(self, proxy_session_id: str) -> Optional[UploadSession]:
        """Retrieves an upload session by its proxy ID."""
        return self.upload_sessions.get(proxy_session_id)

    def save_file_metadata(self, file: FileMetadata):
        """Saves the file metadata to the in-memory store."""
        self.file_metadata_store[file.name] = file
        logging.info(f"Saved metadata for file: {file.name}")

    def get_file_metadata(self, file_name: str) -> Optional[FileMetadata]:
        """Gets file metadata from the in-memory store."""
        return self.file_metadata_store.get(file_name)

    def list_files(self, page_size: int, page_token: Optional[str]) -> dict:
        """Lists all files with pagination."""
        all_files = sorted(self.file_metadata_store.values(), key=lambda f: f.create_time, reverse=True)

        start_index = 0
        if page_token:
            try:
                start_index = int(page_token)
            except ValueError:
                pass  # Invalid token, start from the beginning

        end_index = start_index + page_size
        paginated_files = all_files[start_index:end_index]

        next_page_token = str(end_index) if end_index < len(all_files) else None

        return {
            "files": paginated_files,
            "nextPageToken": next_page_token,
        }

    def delete_file_metadata(self, file_name: str) -> bool:
        """Deletes file metadata from the in-memory store."""
        if file_name in self.file_metadata_store:
            del self.file_metadata_store[file_name]
            logging.info(f"Deleted metadata for file: {file_name}")
            return True
        return False

    def cleanup_session(self, proxy_session_id: str):
        """Cleans up an upload session and its associated temp files."""
        session = self.upload_sessions.pop(proxy_session_id, None)
        if session:
            for chunk_path in session.temp_chunks:
                try:
                    if chunk_path.exists():
                        chunk_path.unlink()
                except OSError as e:
                    logging.error(f"Error deleting temp chunk {chunk_path}: {e}")
            logging.info(f"Cleaned up session {proxy_session_id}")

    async def periodic_cleanup_task(self):
        """Periodically cleans up expired upload sessions."""
        while True:
            await asyncio.sleep(settings.SESSION_CLEANUP_INTERVAL)
            now = datetime.now()
            expired_sessions = [
                session_id
                for session_id, session in self.upload_sessions.items()
                if now - session.created_at > timedelta(seconds=settings.SESSION_EXPIRATION_TIME)
            ]
            if expired_sessions:
                logging.info(f"Found {len(expired_sessions)} expired sessions to clean up.")
                for session_id in expired_sessions:
                    self.cleanup_session(session_id)

    def cleanup_all_temp_files(self):
        """Deletes the entire temporary directory. Called on shutdown."""
        try:
            if self.temp_chunks_dir.exists():
                shutil.rmtree(self.temp_chunks_dir)
                logging.info(f"Successfully removed temporary directory: {self.temp_chunks_dir}")
        except OSError as e:
            logging.error(f"Error removing temporary directory {self.temp_chunks_dir}: {e}")


file_manager = FileManager()
