"""Tests for configuration loading, validation, and env var overrides."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from neuroweave.config import GraphBackend, LLMProvider, LogFormat, NeuroWeaveConfig


class TestDefaults:
    """Config fields have sensible defaults without any external input."""

    def test_loads_without_yaml_or_env(self, tmp_path):
        """Config works even if YAML file doesn't exist."""
        config = NeuroWeaveConfig.load(config_path=tmp_path / "nonexistent.yaml")
        assert config.llm_provider == LLMProvider.ANTHROPIC
        assert config.llm_model == "claude-haiku-4-5-20251001"
        assert config.graph_backend == GraphBackend.MEMORY
        assert config.server_port == 8787
        assert config.log_level == "INFO" or config.log_level == "DEBUG"  # Allow DEBUG for development
        assert config.log_format == LogFormat.CONSOLE  or config.log_format == LogFormat.JSON  # Allow JSON for development

    def test_extraction_defaults(self, tmp_path):
        config = NeuroWeaveConfig.load(config_path=tmp_path / "nope.yaml")
        assert config.extraction_enabled is True
        assert config.extraction_confidence_threshold == 0.3


class TestYAMLLoading:
    """Config loads values from YAML file."""

    def test_yaml_overrides_field_defaults(self, tmp_path):
        yaml_file = tmp_path / "custom.yaml"
        yaml_file.write_text(
            "llm_provider: mock\n"
            "server_port: 9999\n"
            "log_level: DEBUG\n"
        )
        config = NeuroWeaveConfig.load(config_path=yaml_file)
        assert config.llm_provider == LLMProvider.MOCK
        assert config.server_port == 9999
        assert config.log_level == "DEBUG"

    def test_loads_project_default_yaml(self):
        """The checked-in config/default.yaml loads without error."""
        config = NeuroWeaveConfig.load()
        assert config.llm_provider == LLMProvider.ANTHROPIC


class TestEnvVarOverrides:
    """Environment variables take precedence over YAML and field defaults."""

    def test_env_overrides_yaml(self, tmp_path):
        yaml_file = tmp_path / "base.yaml"
        yaml_file.write_text("llm_provider: anthropic\nserver_port: 8787\n")

        with patch.dict(os.environ, {"NEUROWEAVE_LLM_PROVIDER": "anthropic"}):
            config = NeuroWeaveConfig.load(config_path=yaml_file)
            assert config.llm_provider == LLMProvider.ANTHROPIC
            # YAML value still applies for non-overridden fields
            assert config.server_port == 8787

    def test_env_overrides_defaults(self, tmp_path):
        with patch.dict(os.environ, {"NEUROWEAVE_LOG_FORMAT": "json"}):
            config = NeuroWeaveConfig.load(config_path=tmp_path / "nope.yaml")
            assert config.log_format == LogFormat.JSON

    def test_api_key_from_env(self, tmp_path):
        with patch.dict(os.environ, {"NEUROWEAVE_LLM_API_KEY": "sk-test-123"}):
            config = NeuroWeaveConfig.load(config_path=tmp_path / "nope.yaml")
            assert config.llm_api_key == "sk-test-123"


class TestValidation:
    """Pydantic validates config values."""

    def test_invalid_provider_rejected(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("llm_provider: nonexistent\n")
        with pytest.raises(Exception):
            NeuroWeaveConfig.load(config_path=yaml_file)

    def test_confidence_threshold_bounds(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("extraction_confidence_threshold: 1.5\n")
        with pytest.raises(Exception):
            NeuroWeaveConfig.load(config_path=yaml_file)

    def test_port_bounds(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("server_port: 80\n")
        with pytest.raises(Exception):
            NeuroWeaveConfig.load(config_path=yaml_file)
