"""应用配置模块

从环境变量和 .env 文件加载配置。
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置类"""

    # WebSocket 配置
    WEBSOCKET_TIMEOUT: int = 600  # WebSocket 请求超时时间（秒）

    # 代理服务器配置
    PROXY_BASE_URL: str = "http://localhost:8000"  # 代理服务器基础 URL

    # 文件上传配置
    TEMP_CHUNKS_DIR: str = "./temp_chunks"  # 临时文件块存储目录
    SESSION_EXPIRATION_TIME: int = 3600  # 上传会话过期时间（秒），默认 1 小时
    SESSION_CLEANUP_INTERVAL: int = 600  # 会话清理间隔（秒），默认 10 分钟

    class Config:
        env_file = ".env"

settings = Settings()
