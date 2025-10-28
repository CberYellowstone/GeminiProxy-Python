from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    WEBSOCKET_TIMEOUT: int = 600

    class Config:
        env_file = ".env"

settings = Settings()