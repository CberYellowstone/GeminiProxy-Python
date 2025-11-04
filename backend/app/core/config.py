"""应用配置模块

从环境变量和 .env 文件加载配置。
"""

import os
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类

    从 .env 文件和环境变量加载配置。
    环境变量优先级高于 .env 文件。
    """

    # ===========================
    # 应用配置
    # ===========================
    APP_ENV: str = "development"  # 应用环境: development, production
    LOG_LEVEL: str = "INFO"  # 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL

    # ===========================
    # 服务器配置
    # ===========================
    PROXY_BASE_URL: str = "http://localhost:8000"  # 代理服务器基础 URL

    # ===========================
    # WebSocket 配置
    # ===========================
    WEBSOCKET_TIMEOUT: int = 600  # WebSocket 请求超时时间（秒）

    # ===========================
    # CORS 配置
    # ===========================
    CORS_ORIGINS: str = "*"  # 允许的跨域源，多个用逗号分隔
    CORS_ALLOW_CREDENTIALS: bool = True  # 是否允许携带凭证

    # ===========================
    # 文件上传配置
    # ===========================
    TEMP_CHUNKS_DIR: str = "./temp_chunks"  # 临时文件块存储目录
    SESSION_EXPIRATION_TIME: int = 3600  # 上传会话过期时间（秒）
    SESSION_CLEANUP_INTERVAL: int = 600  # 会话清理间隔（秒）

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"  # 忽略未定义的环境变量
    )

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """验证日志级别"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"LOG_LEVEL 必须是 {valid_levels} 之一")
        return v_upper

    @field_validator("APP_ENV")
    @classmethod
    def validate_app_env(cls, v: str) -> str:
        """验证应用环境"""
        valid_envs = ["development", "production"]
        v_lower = v.lower()
        if v_lower not in valid_envs:
            raise ValueError(f"APP_ENV 必须是 {valid_envs} 之一")
        return v_lower

    @field_validator("TEMP_CHUNKS_DIR")
    @classmethod
    def validate_temp_dir(cls, v: str) -> str:
        """验证并创建临时目录"""
        path = Path(v)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return v

    def get_cors_origins(self) -> List[str]:
        """获取 CORS 允许的源列表"""
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.APP_ENV == "development"

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.APP_ENV == "production"


# 创建全局配置实例
settings = Settings()
