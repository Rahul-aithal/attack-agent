from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATTACK_AGENT_", env_file=".env", extra="ignore"
    )

    model_name: str = "llama3.2:3b"
    ollama_host: str = "http://localhost:11434"
    temperature: float = 0.7
    analysis_temperature: float = 0.2
    request_timeout: float = 180.0

    min_turns: int = 8
    max_turns: int = 20
    trait_confidence_threshold: float = 0.5
    min_traits_above_threshold: int = 4
    avg_confidence_threshold: float = 0.55
    stability_threshold: float = 0.75

    output_dir: Path = Path("outputs")

    log_dir: Path = Path("outputs/logs")


@lru_cache
def get_settings() -> Settings:
    return Settings()
