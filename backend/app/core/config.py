from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    WEBSOCKET_TIMEOUT: int = 600
    PROXY_BASE_URL: str = "http://localhost:8000"

    TEMP_CHUNKS_DIR: str = "./temp_chunks"

    class Config:
        env_file = ".env"

settings = Settings()
