"""Configuration settings for Go Live Coach without external pydantic_settings dependency."""
import os
from pathlib import Path
from dataclasses import dataclass

@dataclass
class Settings:
    PORT: int = int(os.getenv("PORT", "8095"))
    HOST: str = os.getenv("HOST", "127.0.0.1")
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "./data"))

    COACH_PROVIDER: str = os.getenv("COACH_PROVIDER", "rule-fallback")
    COACH_MODEL: str = os.getenv("COACH_MODEL", "gemini-2.5-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    KATAGO_PATH: Path = Path(os.getenv("KATAGO_PATH", "/opt/homebrew/bin/katago"))
    KATAGO_MODEL: Path = Path(os.getenv("KATAGO_MODEL", "/opt/homebrew/share/katago/kata1-b18c384nbt-s9996604416-d4316597426.bin.gz"))
    KATAGO_MAX_VISITS: int = int(os.getenv("KATAGO_MAX_VISITS", "150"))
    KATAGO_THREADS: int = int(os.getenv("KATAGO_THREADS", "2"))
    KATAGO_MAX_BATCH_SIZE: int = int(os.getenv("KATAGO_MAX_BATCH_SIZE", "16"))

    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:8095,http://localhost:8095")

def load_settings() -> Settings:
    env_file = Path(".env")
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k not in os.environ:
                        os.environ[k] = v
    return Settings()

settings = load_settings()
