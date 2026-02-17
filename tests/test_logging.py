"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging
from io import StringIO
from unittest.mock import patch

import structlog

from neuroweave.config import LogFormat, NeuroWeaveConfig
from neuroweave.logging import configure_logging, get_logger


def _make_config(**overrides) -> NeuroWeaveConfig:
    """Create a config with defaults, applying overrides."""
    defaults = {
        "llm_provider": "mock",
        "log_level": "DEBUG",
        "log_format": "console",
    }
    defaults.update(overrides)
    return NeuroWeaveConfig(**defaults)


def _capture_log_output(config: NeuroWeaveConfig, log_fn) -> str:
    """Configure logging, run log_fn, return captured stderr output."""
    configure_logging(config)

    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.getLogger().handlers[0].formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)

    log_fn()

    handler.flush()
    return stream.getvalue()


class TestConfigureLogging:
    """configure_logging sets up structlog correctly."""

    def test_console_format_produces_output(self):
        config = _make_config(log_format="console")
        output = _capture_log_output(
            config,
            lambda: structlog.get_logger().info("test.event", key="value"),
        )
        assert "test.event" in output
        assert "key" in output

    def test_json_format_produces_valid_json(self):
        config = _make_config(log_format="json")
        output = _capture_log_output(
            config,
            lambda: structlog.get_logger().info("test.event", count=42),
        )
        parsed = json.loads(output.strip())
        print(parsed)
        assert parsed["event"] == "test.event"
        assert parsed["count"] == 42
        assert "timestamp" in parsed
        assert parsed["level"] == "info"  # Allow uppercase for development

    def test_log_level_filtering(self):
        config = _make_config(log_level="WARNING")
        output = _capture_log_output(
            config,
            lambda: structlog.get_logger().info("should.not.appear"),
        )
        assert output.strip() == ""

    def test_log_level_passes_at_threshold(self):
        config = _make_config(log_level="WARNING")
        output = _capture_log_output(
            config,
            lambda: structlog.get_logger().warning("should.appear"),
        )
        assert "should.appear" in output

    def test_noisy_loggers_suppressed(self):
        config = _make_config(log_level="DEBUG")
        configure_logging(config)
        uvicorn_level = logging.getLogger("uvicorn").getEffectiveLevel()
        assert uvicorn_level >= logging.WARNING


class TestGetLogger:
    """get_logger returns properly bound loggers."""

    def test_unbound_logger(self):
        config = _make_config()
        configure_logging(config)
        log = get_logger()
        assert log is not None

    def test_bound_logger_includes_component(self):
        config = _make_config(log_format="json")
        output = _capture_log_output(
            config,
            lambda: get_logger("extraction").info("pipeline.start"),
        )
        parsed = json.loads(output.strip())
        assert parsed["component"] == "extraction"
        assert parsed["event"] == "pipeline.start"

    def test_bound_logger_with_extra_context(self):
        config = _make_config(log_format="json")
        output = _capture_log_output(
            config,
            lambda: get_logger("graph").info("node.added", node_type="entity", name="Lena"),
        )
        parsed = json.loads(output.strip())
        assert parsed["component"] == "graph"
        assert parsed["node_type"] == "entity"
        assert parsed["name"] == "Lena"
