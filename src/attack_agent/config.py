"""Runtime settings.

Every tunable constant lives here so experiments can sweep them. Values come from (in order of
precedence) environment variables prefixed ``ATTACK_AGENT_``, a ``.env`` file, then the defaults
below. Model routing across machines is configured separately in ``deploy.yaml`` (see
``deploy.example.yaml``); when that file is absent every role uses ``ollama_host`` + ``model_name``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATTACK_AGENT_", env_file=".env", extra="ignore")

    # ---- single-machine defaults (used when deploy.yaml is absent) ----
    model_name: str = "llama3.2:3b"
    ollama_host: str = "http://localhost:11434"
    deploy_file: Path = Path("deploy.yaml")

    # ---- LLM call behaviour ----
    temperature: float = 0.7
    analysis_temperature: float = 0.2
    request_timeout: float = 180.0
    health_timeout: float = 4.0
    health_cache_seconds: float = 20.0
    json_repair_retries: int = 1

    # ---- profiling stop rule ----
    min_turns: int = 8
    max_turns: int = 20
    trait_confidence_threshold: float = 0.5
    min_traits_above_threshold: int = 4
    avg_confidence_threshold: float = 0.55
    stability_threshold: float = 0.75
    stopping_rule: bool = True  # False => always run to max_turns (ablation)

    # ---- profiler (v2 Beta posterior) ----
    profiler_version: Literal["beta", "v1"] = "beta"
    beta_prior_alpha: float = 2.0
    beta_prior_beta: float = 2.0
    beta_evidence_weight: float = 1.5
    beta_contradiction_penalty: float = 0.5
    max_confidence: float = 0.95
    stability_window: int = 4
    stability_scale: float = 5.0
    # v1 (legacy, kept for ablation)
    v1_step: float = 0.18
    v1_confidence_rate: float = 0.35

    # ---- signal extraction ----
    extractor_mode: Literal["llm", "keyword"] = "llm"
    min_evidence_strength: float = 0.4
    keyword_min_hits: int = 2

    # ---- strategy / scenario ----
    strategy_map_file: Path | None = None  # None => packaged config/strategy_map.yaml
    selection_mode: str = "literature_map"  # literature_map | twin_driven | random | fixed:<principle>
    scenario_max_exchanges: int = 2
    safety_max_regenerations: int = 3
    simulated_domain: str = "portal.simulated-link.example.com"

    # ---- session flow ----
    questionnaire_enabled: bool = True
    twin_enabled: bool = True

    # ---- storage / outputs ----
    output_dir: Path = Path("outputs")
    log_dir: Path = Path("outputs/logs")
    database_url: str = "sqlite:///outputs/attack_agent.db"

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    admin_token: str = ""  # empty => random token generated and printed at startup
    public_sessions: bool = True  # participants may start a session without the admin token
    cors_origins: str = "*"
    web_dist: Path = Path("web/dist")


@lru_cache
def get_settings() -> Settings:
    return Settings()
