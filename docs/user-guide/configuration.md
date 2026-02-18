# Configuration

NeuroWeave uses a three-tier configuration system: **field defaults → YAML file → environment variables** (highest priority).

## Configuration Methods

### Programmatic (recommended for library use)

```python
from neuroweave import NeuroWeave

nw = NeuroWeave(
    llm_provider="anthropic",
    llm_api_key="sk-ant-...",
    llm_model="claude-haiku-4-5-20251001",
    enable_visualization=True,
    server_port=8787,
    log_level="INFO",
    log_format="console",
)
```

### YAML File

```python
nw = NeuroWeave.from_config("config/default.yaml")
```

```yaml title="config/default.yaml"
llm_provider: "anthropic"
llm_model: "claude-haiku-4-5-20251001"
extraction_enabled: true
extraction_confidence_threshold: 0.3
graph_backend: "memory"
server_host: "127.0.0.1"
server_port: 8787
log_level: "INFO"
log_format: "console"
```

### Environment Variables

All fields can be overridden with `NEUROWEAVE_` prefixed environment variables:

```bash
export NEUROWEAVE_LLM_PROVIDER=mock
export NEUROWEAVE_LLM_API_KEY=sk-ant-...
export NEUROWEAVE_LOG_FORMAT=json
export NEUROWEAVE_SERVER_PORT=9000
```

The API key is also read from `ANTHROPIC_API_KEY` for convenience.

## All Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `llm_provider` | `"anthropic"` \| `"mock"` | `"anthropic"` | LLM backend for extraction |
| `llm_model` | `str` | `"claude-haiku-4-5-20251001"` | Model identifier |
| `llm_api_key` | `str` | `""` | API key (required for anthropic provider) |
| `extraction_enabled` | `bool` | `true` | Enable/disable extraction pipeline |
| `extraction_confidence_threshold` | `float` | `0.3` | Minimum confidence to store a relation |
| `graph_backend` | `"memory"` | `"memory"` | Graph storage backend |
| `server_host` | `str` | `"127.0.0.1"` | Visualization server bind address |
| `server_port` | `int` | `8787` | Visualization server port |
| `log_level` | `str` | `"INFO"` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `log_format` | `"console"` \| `"json"` | `"console"` | Log output format |

## Logging

NeuroWeave uses [structlog](https://www.structlog.org/) for structured logging.

**Console mode** (development) — colored, human-readable output:

```
2026-02-17 10:30:15 [info] extraction.complete  entity_count=3 relation_count=2 duration_ms=47.2
```

**JSON mode** (production) — machine-parseable output:

```json
{"event": "extraction.complete", "entity_count": 3, "relation_count": 2, "duration_ms": 47.2, "timestamp": "2026-02-17T10:30:15Z"}
```

Set via `log_format="json"` or `NEUROWEAVE_LOG_FORMAT=json`.
