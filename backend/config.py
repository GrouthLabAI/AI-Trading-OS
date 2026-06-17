# AI Trading OS - Configuration
import os
from pathlib import Path
from pydantic_settings import BaseSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # LLM
    llm_provider: str = "claude"  # claude | gpt | deepseek | glm | gemini
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")

    # Database
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT}/database/trading.db"

    # ChromaDB
    chroma_persist_dir: str = str(PROJECT_ROOT / "vector_db")

    # Feishu (飞书) Integration
    feishu_app_id: str = os.getenv("FEISHU_APP_ID", "")
    feishu_app_secret: str = os.getenv("FEISHU_APP_SECRET", "")
    feishu_bitable_id: str = os.getenv("FEISHU_BITABLE_ID", "")        # Bitable doc token
    feishu_table_trade_plan: str = os.getenv("FEISHU_TABLE_TRADE_PLAN", "")  # Trade plan table ID
    feishu_table_review: str = os.getenv("FEISHU_TABLE_REVIEW", "")          # Review table ID

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
