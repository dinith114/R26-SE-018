"""
Application configuration settings.
"""

import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App
    APP_NAME: str = "Smart Orchid Care API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Firebase
    FIREBASE_CREDENTIALS_PATH: str = ""
    FIREBASE_DATABASE_URL: str = ""

    # ML Models
    MODEL_PATH: str = os.path.join(os.path.dirname(__file__), "..", "..", "..", "ml-models")

    class Config:
        env_file = ".env"


settings = Settings()
