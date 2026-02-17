"""NeuroWeave configuration — single source of truth for all settings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOCK = "mock"


class LogFormat(str, Enum):
    CONSOLE = "console"
    JSON = "json"


class GraphBackend(str, Enum):
    MEMORY = "memory"


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "default.yaml"


def _load_yaml_defaults(path: Path) -> dict[str, Any]:
    """Load default values from YAML config file."""
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class NeuroWeaveConfig(BaseSettings):
    """All NeuroWeave configuration.

    Loading priority (highest wins):
        1. Environment variables (NEUROWEAVE_*)
        2. .env file
        3. config/default.yaml
        4. Field defaults below
    """

    model_config = SettingsConfigDict(
        env_prefix="NEUROWEAVE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    llm_provider: LLMProvider = LLMProvider.ANTHROPIC
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_api_key: str = ""

    # --- Extraction ---
    extraction_enabled: bool = True
    extraction_confidence_threshold: float = Field(default=0.3, ge=0.0, le=1.0)

    # --- Graph ---
    graph_backend: GraphBackend = GraphBackend.MEMORY

    # --- Server ---
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8787, ge=1024, le=65535)

    # --- Logging ---
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    @classmethod
    def load(cls, config_path: Path | None = None) -> NeuroWeaveConfig:
        """Load config with YAML defaults, then env var overrides.

        Args:
            config_path: Path to YAML config file. Defaults to config/default.yaml.
        """
        yaml_path = config_path or _DEFAULT_CONFIG
        yaml_values = _load_yaml_defaults(yaml_path)
        return cls(**yaml_values)
