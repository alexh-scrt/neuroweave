<p align="center">
  <img src="assets/image.png" alt="NeuroWeave" width="200"/>
</p>

<h1 align="center">NeuroWeave</h1>

<p align="center">
  <strong>Real-time knowledge graph memory for agentic AI platforms.</strong>
</p>

<p align="center">
  <em>Agents that learn. Memory that compounds. Privacy that's provable.</em>
</p>

<p align="center">
  <a href="#quickstart">Quickstart</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#features">Features</a> •
  <a href="#api-reference">API</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <a href="https://github.com/user/neuroweave/actions"><img src="https://img.shields.io/github/actions/workflow/status/user/neuroweave/ci.yml?branch=master&style=flat-square" alt="CI"></a>
  <a href="https://pypi.org/project/neuroweave/"><img src="https://img.shields.io/pypi/v/neuroweave?style=flat-square" alt="PyPI"></a>
  <a href="https://github.com/user/neuroweave/blob/master/LICENSE"><img src="https://img.shields.io/github/license/user/neuroweave?style=flat-square" alt="License"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square" alt="Python 3.11+"></a>
  <a href="https://discord.gg/neuroweave"><img src="https://img.shields.io/discord/0000000000?style=flat-square&label=discord" alt="Discord"></a>
</p>

---

## The Problem

Every agentic platform claims to have memory. What they actually have is a **log**.

Most agent memory systems store conversation history as sequential text. When the agent needs context, it performs retrieval over past messages. This is fundamentally **recall**, not **understanding**. The agent can retrieve what was said — it cannot reason about what was learned.

An agent that merely recalls conversations will repeat questions the user already answered in a different context, fail to connect insights across separate interactions, treat each skill invocation as isolated with no accumulated expertise, and have no model of the user beyond keyword matching over transcripts.

**NeuroWeave replaces this with Experience Memory** — a graph-based, structured, evolving representation of everything an agent learns through interaction, observation, and action. The agent doesn't just remember. It *knows*.

---

## Three Layers of Agent Knowledge

| Layer | What It Stores | How It's Used | Who Has It |
|-------|---------------|---------------|------------|
| **Recall** | Raw conversation transcripts | Keyword search, RAG retrieval | Most agent platforms |
| **Understanding** | Entities, relationships, facts | Structured queries, fact lookup | Some enterprise platforms |
| **Experience** | Learned behaviors, patterns, procedures, preferences, causal models | Anticipation, adaptation, transfer learning across contexts | **NeuroWeave** |

NeuroWeave operates across all three layers, with **Experience Memory** as the primary differentiator.

---

## Features

- **Typed temporal knowledge graph** — Entities, concepts, episodes, experiences, procedures, and preferences stored in Neo4j with confidence scores, temporal metadata, and decay tracking on every edge
- **Continuous extraction pipeline** — Every user interaction is processed through a multi-stage NLU pipeline (entity extraction → relation extraction → sentiment/hedging → temporal scoping → confidence scoring → graph diff) running on a fast small LLM
- **Four acquisition mechanisms** — Explicit statements, behavioral observation, cross-context inference, and agent self-reflection each feed the graph at calibrated confidence levels
- **Proactive intelligence** — Contextual probing to fill knowledge gaps, conversation starters triggered by external events (weather, news, calendar), and anticipatory suggestions — all governed by a risk model
- **Confidence lifecycle** — Knowledge isn't permanent. Edges are reinforced by repeated evidence, decay without reinforcement, get revised on contradiction, and are archived when stale
- **Privacy-first architecture** — Designed to run inside Confidential VMs (hardware-encrypted memory isolation). Four-level privacy classification (Public → Platform → Personal → Sealed). Full GDPR compliance with right to access, rectification, erasure, and data portability
- **Experience sharing** — Privacy-preserving transfer of anonymized procedural knowledge between agents via a shared experience pool with differential privacy. New agents bootstrap with collective intelligence from Day 1
- **MCP interface** — Standard Model Context Protocol tools for seamless integration with any MCP-compatible agent runtime
- **Dual LLM strategy** — Small/fast LLM for real-time extraction, large LLM for overnight inference and experience synthesis. Configurable token budgets per model
- **Resilient by design** — Circuit breakers on every dependency, graceful degradation (agent works without EM context), poison message handling with dead letter queues, idempotent processing

---

## Architecture

NeuroWeave is a **service** that happens to have an MCP interface, not an MCP server that happens to have background processing.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Experience Memory Service                        │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ API Layer                                                       │    │
│  │  ┌──────────────────┐  ┌──────────────────────────────────┐    │    │
│  │  │   MCP Interface   │  │   gRPC / Internal API            │    │    │
│  │  │  (Agent queries)  │  │  (High-throughput ingestion)     │    │    │
│  │  └────────┬─────────┘  └──────────────┬───────────────────┘    │    │
│  └───────────┼───────────────────────────┼────────────────────────┘    │
│              │                           │                              │
│  ┌───────────┼───────────────────────────┼────────────────────────┐    │
│  │ Processing Core                       │                         │    │
│  │  ┌────────▼─────────┐  ┌─────────────▼──────────────────┐     │    │
│  │  │    Extraction     │  │        Graph Diff Engine        │     │    │
│  │  │    Pipeline       │──│  (New vs Reinforce vs Contra.)  │     │    │
│  │  └──────────────────┘  └──────────────┬─────────────────┘     │    │
│  │  ┌──────────────────┐  ┌──────────────▼─────────────────┐     │    │
│  │  │ Inference Engine  │  │      Proactive Engine          │     │    │
│  │  │ (Cross-context)   │  │  (Probes, starters, triggers)  │     │    │
│  │  └──────────────────┘  └────────────────────────────────┘     │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Background Workers                                              │    │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────┐ ┌────────────┐  │    │
│  │  │ Revision  │ │ Inference │ │ Event Monitor │ │ Scheduler  │  │    │
│  │  │ Worker    │ │ Worker    │ │ (News/Weather)│ │ (Cron)     │  │    │
│  │  └──────────┘ └───────────┘ └──────────────┘ └────────────┘  │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ Storage Layer                                                    │    │
│  │  ┌──────────┐ ┌────────────┐ ┌───────────┐ ┌───────────────┐ │    │
│  │  │  Neo4j   │ │Vector Store│ │ Inbound Q │ │  Outbound Q   │ │    │
│  │  │  (Graph) │ │ (Episodes) │ │  (Redis)  │ │   (Redis)     │ │    │
│  │  └──────────┘ └────────────┘ └───────────┘ └───────────────┘ │    │
│  └────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │ LLM Access                                                       │    │
│  │  ┌─────────────────────┐  ┌──────────────────────────────┐    │    │
│  │  │ Small/Fast LLM       │  │ Large LLM                    │    │    │
│  │  │ (Extraction, hedge)  │  │ (Inference, synthesis)       │    │    │
│  │  └─────────────────────┘  └──────────────────────────────┘    │    │
│  └────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Component Overview

| Component | Role | Technology |
|-----------|------|------------|
| **Extraction Pipeline** | Multi-stage NLU: tokenization → entity extraction → relation extraction → sentiment/hedging → temporal scoping → confidence scoring → graph diff | Python, Small LLM (Haiku-class) |
| **Graph Diff Engine** | Determines whether extracted knowledge is new (INSERT), reinforcing (REINFORCE), contradictory (CONTRADICT), or redundant (SKIP) | Python, Neo4j Cypher |
| **Proactive Engine** | Evaluates triggers, generates contextual probes, manages conversation starters, applies risk model to decide action thresholds | Python |
| **Inference Engine** | Discovers cross-context patterns and causal chains through multi-hop graph reasoning | Python, Large LLM (Sonnet-class) |
| **Background Workers** | Overnight fact revision, confidence decay, inference chain discovery, event monitoring | Python, APScheduler |
| **MCP Server** | Exposes `em_query`, `em_report_interaction`, `em_get_probes`, `em_get_starters`, `em_user_correction`, `em_get_provenance`, `em_graph_snapshot` | Python, MCP SDK |
| **Knowledge Graph** | Typed, temporal, weighted graph with confidence-tracked edges and temporal metadata | Neo4j |
| **Vector Store** | Episode embeddings for semantic similarity search across past interactions | Qdrant / Chroma |
| **Queues** | Inbound (interaction events) and outbound (probes, starters, suggestions) with priority and TTL | Redis Streams |

### Dual LLM Strategy

| Task | LLM | Rationale |
|------|-----|-----------|
| Entity & relation extraction | Small/Fast | Runs on every message, needs < 200ms latency |
| Hedging & confidence detection | Small/Fast | Classification task, structured output |
| Contradiction resolution | Large | Requires nuanced semantic reasoning |
| Overnight inference chains | Large | Creative cross-domain pattern discovery |
| Experience synthesis | Large | Generalizes episodes into reusable knowledge |
| Probe question generation | Large | Needs conversational naturalness |

---

## Graph Model

### Node Types

| Node Type | Description | Examples |
|-----------|-------------|----------|
| **Entity** | People, organizations, tools, places | User, Acme Corp, Python, Tokyo |
| **Concept** | Abstract ideas, domains, topics | Machine learning, budget optimization |
| **Episode** | A specific interaction or event with temporal bounds | "Debugged OAuth issue on Jan 15" |
| **Experience** | A learned pattern derived from one or more episodes | "User prefers error logs before suggestions" |
| **Procedure** | A multi-step workflow the agent has learned or refined | "Code review: lint → test → diff → summary" |
| **Preference** | An explicit or inferred user preference | "Prefers concise responses before 10am" |
| **Context** | Environmental or situational metadata | "Q1 crunch", "Pre-launch week" |

### Edge Properties

Every edge carries metadata enabling temporal reasoning and confidence decay:

```
relation:         Typed relationship (prefers, knows, works_at, learned_from, ...)
confidence:       0.0–1.0, increases with reinforcement, decays over time
first_observed:   Timestamp of initial discovery
last_reinforced:  Timestamp of most recent supporting evidence
source_episodes:  Links to the interactions that established this edge
decay_rate:       Per-category degradation rate without reinforcement
context_tags:     Situational tags scoping when this edge is relevant
```

### Experience Types

| Type | What It Captures | Example |
|------|-----------------|---------|
| **Procedural** | How to accomplish a task effectively | "When deploying Python services, always run mypy before pytest" |
| **Preferential** | How the user likes things done | "Prefers diff-style code reviews with 3 lines of context" |
| **Causal** | Cause-and-effect patterns observed over time | "When Slack status is 🔴, response times increase 4x → batch non-urgent items" |
| **Social** | Interaction patterns with specific people/teams | "Meetings with Team X always start 5min late → add buffer" |
| **Temporal** | Time-based patterns and rhythms | "Deep work 6–10am, meetings 10am–1pm, admin 2–4pm" |
| **Environmental** | Context-dependent behavior changes | "During travel: brief mobile-friendly responses" |

---

## Quickstart

### Prerequisites

- Python 3.11+
- Neo4j 5.x
- Redis 7.x
- Qdrant (or Chroma) for vector storage

### Installation

```bash
pip install neuroweave
```

Or from source:

```bash
git clone https://github.com/user/neuroweave.git
cd neuroweave
pip install -e ".[dev]"
```

### Docker Compose (recommended for development)

```bash
# Start all dependencies
docker compose up -d

# Run NeuroWeave
neuroweave serve --config config/experience_memory.yaml
```

```yaml
# docker-compose.yml
services:
  neo4j:
    image: neo4j:5-community
    ports:
      - "7687:7687"
      - "7474:7474"
    environment:
      NEO4J_AUTH: neo4j/neuroweave_dev

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"

  neuroweave:
    build: .
    depends_on: [neo4j, redis, qdrant]
    ports:
      - "8420:8420"
    volumes:
      - ./config:/app/config
```

### Verify Installation

```bash
neuroweave health
# ✓ Neo4j ........... connected (bolt://localhost:7687)
# ✓ Redis ........... connected (redis://localhost:6379)
# ✓ Vector Store .... connected (http://localhost:6333)
# ✓ MCP Server ...... listening on :8420
# ✓ Background ....... 3 workers running
```

---

## API Reference

NeuroWeave exposes its functionality through MCP tools, making it compatible with any MCP-enabled agent runtime.

### MCP Tools

#### `em_query` — Query the knowledge graph

```json
{
  "tool": "em_query",
  "params": {
    "entity": "Lena",
    "min_confidence": 0.5,
    "max_hops": 2,
    "include_experiences": true
  }
}
```

Returns a subgraph of entities, edges, and experiences relevant to the query, filtered by confidence and scoped by hop distance.

#### `em_report_interaction` — Report a conversation turn for processing

```json
{
  "tool": "em_report_interaction",
  "params": {
    "text": "She absolutely loves Malbec",
    "entities_mentioned": ["Lena", "Malbec"],
    "session_id": "sess_abc123",
    "turn_number": 7,
    "channel": "telegram"
  }
}
```

Enqueues the interaction for asynchronous extraction. The agent does **not** wait for processing to complete.

#### `em_get_probes` — Pull pending contextual probes

```json
{
  "tool": "em_get_probes",
  "params": {
    "active_topics": ["wine", "gifts"],
    "entities_in_scope": ["Lena"]
  }
}
```

Returns probes whose context tags match the current conversation. The agent decides whether and when to deliver them.

#### `em_get_starters` — Pull pending conversation starters

```json
{
  "tool": "em_get_starters",
  "params": {
    "channel": "telegram",
    "max_results": 3
  }
}
```

Returns starters (weather alerts, birthday reminders, deal notifications) ready for delivery on the specified channel.

#### `em_user_correction` — Apply a user's correction

```json
{
  "tool": "em_user_correction",
  "params": {
    "correction_type": "revise",
    "entity": "Lena",
    "field": "age",
    "old_value": "47",
    "new_value": "46"
  }
}
```

Immediately updates the graph. Supports `revise`, `delete`, and `retract` correction types.

#### `em_get_provenance` — Explain how the agent knows something

```json
{
  "tool": "em_get_provenance",
  "params": {
    "edge_id": "edge_00482"
  }
}
```

Returns the full provenance chain: source episodes, timestamps, acquisition mechanism, and reinforcement history.

#### `em_graph_snapshot` — Export the full knowledge graph

```json
{
  "tool": "em_graph_snapshot",
  "params": {
    "format": "full"
  }
}
```

Exports the complete graph as JSON or GraphML. Supports GDPR data portability requirements.

---

## Configuration

NeuroWeave uses a YAML configuration file organized into sensible defaults, user-facing profile settings, and expert overrides. Most settings are hot-reloadable without service restart.

### Minimal Configuration

```yaml
# experience_memory.yaml
profile:
  timezone: "America/Los_Angeles"
  language: "en"
  proactivity_level: "balanced"   # conservative | balanced | proactive

llm:
  small:
    provider: "anthropic"
    model: "claude-haiku-4-5-20251001"
  large:
    provider: "anthropic"
    model: "claude-sonnet-4-5-20250929"

storage:
  neo4j:
    uri: "bolt://localhost:7687"
  vector_store:
    provider: "qdrant"
    uri: "http://localhost:6333"
  queue:
    provider: "redis"
    uri: "redis://localhost:6379"
```

### Proactivity Presets

The `proactivity_level` maps to a coherent set of behavioral defaults:

| Setting | Conservative | Balanced | Proactive |
|---------|-------------|----------|-----------|
| Probes per conversation | 0 | 1 | 2 |
| Probes per week | 3 | 10 | 20 |
| Context-fit threshold | 0.90 | 0.70 | 0.50 |
| Conversation starters | Disabled | Enabled (3/day) | Enabled (5/day) |
| Indirect inference | Disabled | Enabled | Enabled |
| Auto-execute threshold | 0.99 | 0.90 | 0.80 |

Every individual setting can be overridden beyond the preset.

### Key Configuration Sections

<details>
<summary><strong>Extraction</strong> — Controls how facts are extracted from conversations</summary>

```yaml
extraction:
  enable_indirect_inference: true
  min_storage_confidence: 0.25
  max_entities_per_message: 20
  max_relations_per_message: 30
  enable_sentiment: true
  stt_confidence_floor: 0.70
  stt_confidence_scale: true
```
</details>

<details>
<summary><strong>Confidence</strong> — Controls the confidence scoring model</summary>

```yaml
confidence:
  base_scores:
    explicit: 0.90
    observational: 0.65
    inferential: 0.45
    reflective: 0.50
  hedge_multipliers:
    none: 1.00
    mild: 0.90
    moderate: 0.65
    strong: 0.50
  reinforcement_boost: 0.08
  max_confidence: 0.99
  archive_threshold: 0.15
```
</details>

<details>
<summary><strong>Decay</strong> — Controls how knowledge ages</summary>

```yaml
decay:
  default_rate: 0.02          # 2% per month
  rates_by_type:
    trait: 0.005              # Near-permanent
    state: 0.00               # Only contradictions
    wish: 0.04                # Time-bounded desires
    episode: 0.08             # One-time events
  cycle_frequency: "weekly"
  grace_period_days: 30
```
</details>

<details>
<summary><strong>Probing</strong> — Controls contextual probing behavior</summary>

```yaml
probing:
  max_probes_per_conversation: 1
  max_probes_per_day: 3
  max_probes_per_week: 10
  min_turn_for_probe: 3
  min_context_fit: 0.70
  ignore_cooldown_days: 7
  deflect_cooldown_days: 14
```
</details>

<details>
<summary><strong>Background Workers</strong> — Controls revision and inference scheduling</summary>

```yaml
background:
  revision_schedule: "0 2 * * *"      # 2 AM daily
  inference_schedule: "0 3 * * *"     # 3 AM daily
  clustering_schedule: "0 4 * * 0"    # 4 AM Sundays
  revision_batch_size: 100
  max_inference_depth: 3
  enable_public_fact_verification: true
```
</details>

<details>
<summary><strong>Privacy</strong> — Controls data classification and experience sharing</summary>

```yaml
privacy:
  sharing_enabled: false            # Opt-in only
  sharing_min_level: "L1"           # Only L0-L1 shared
  differential_privacy: true
  dp_epsilon: 1.0
  auto_pii_detection: true
  archive_retention_days: 365
```
</details>

For the complete configuration reference with all 80+ knobs, see [`docs/configuration.md`](docs/configuration.md).

---

## Privacy & Security

NeuroWeave is designed to run inside **Confidential VMs** — hardware-encrypted memory isolation where not even the host operator can access the contents.

### Four-Level Privacy Classification

| Level | Description | Shareable | Example |
|-------|-------------|-----------|---------|
| **L0 — Public** | General knowledge, world facts | ✅ Yes | "Python 3.12 supports type parameter syntax" |
| **L1 — Platform** | Anonymized procedural knowledge | ✅ Yes (anonymized) | "Multi-step API integration: steps 1–5" |
| **L2 — Personal** | User preferences, non-identifying patterns | ⚠️ Consent only | "Owner prefers morning meetings" |
| **L3 — Private** | PII, specific facts about the user | ❌ Never | "User is John Smith, CTO of Acme Corp" |
| **L4 — Sealed** | Credentials, secrets, sensitive content | ❌ Cryptographically sealed | API keys, OAuth tokens |

### GDPR Compliance

NeuroWeave implements all relevant GDPR data subject rights:

- **Right to Access (Art. 15)** — Full graph export via `em_graph_snapshot` in machine-readable JSON or GraphML
- **Right to Rectification (Art. 16)** — `em_user_correction` tool for in-conversation corrections, plus UI-based fact management
- **Right to Erasure (Art. 17)** — Single fact, single entity, or full graph wipe with deletion propagation across all six storage locations and a cryptographic deletion certificate
- **Right to Data Portability (Art. 20)** — Version-stable export format documented for cross-system migration

### Threat Model

NeuroWeave defends against six categories of threats:

| Threat | Mitigation |
|--------|-----------|
| Prompt injection via extraction | Input sanitization, prompt hardening, credential detection |
| Data poisoning | Confidence lifecycle prevents bypass, contradiction detection after 3+ conflicts |
| Knowledge extraction attacks | Skill sandboxing (no direct graph access), output PII scanning, group chat mode suppression |
| LLM hallucination | Span verification, entity count sanity, context bleed detection |
| Stale data harm | Per-category decay rates, periodic probing, background revision with web verification |
| Audit trail exposure | Metadata-only audit records, deletion records contain no original content |

---

## Experience Sharing

NeuroWeave's most distinctive capability: **privacy-preserving transfer of procedural knowledge between agents**.

### What Transfers vs. What Stays Local

| Knowledge Category | Shareable | Reason |
|--------------------|-----------|--------|
| Procedural knowledge ("How to do X well") | ✅ | Generic skill, no PII |
| Domain patterns ("FinTech Q1 = reporting season") | ✅ | Industry knowledge |
| Tool expertise ("MCP skill X works best with params Y") | ✅ | Platform knowledge |
| User preferences | ❌ | Personal, stays in user's CVM |
| User facts / PII | ❌ | Never leaves CVM |
| Conversation content | ❌ | Private, never leaves CVM |
| Credentials and secrets | ❌ | Cryptographically sealed to CVM |

Shared knowledge enters new agents at **low confidence (0.30)** and must be independently reinforced by that user's own interactions before reaching action thresholds. Differential privacy is applied before any data leaves the CVM.

### The Network Effect

A new user's agent on Day 1 already has access to the distilled procedural knowledge of every agent that came before it — without accessing any other user's private data. This creates a compounding advantage: every agent makes all agents better.

---

## Cold Start

NeuroWeave handles the empty-graph problem gracefully. The agent works normally from interaction one — it simply gets smarter over time.

### Maturity Stages

| Stage | Requirements | Typical Timeline | Capability |
|-------|-------------|-----------------|------------|
| **Empty** | CVM provisioned, EM initialized | Day 0 | Agent works, no personalization |
| **Learning** | First conversations | Days 1–3 | Aggressive extraction from natural conversation |
| **MinViable** | ~10 interactions, ~20 edges, ~5 entities | ~1 week | Basic personalization, first "it knows me" moments |
| **Functional** | ~30 interactions, ~80 edges | ~2 weeks | Contextual probing active, cross-session knowledge |
| **Mature** | ~100 interactions, experiences forming | ~1 month | Anticipatory behavior, proactive suggestions |
| **Expert** | ~500+ interactions, procedures learned | ~3 months | Deep anticipation, procedure learning, network effects |

### Optional Onboarding Accelerators

For users who want to fast-track the learning process, NeuroWeave supports optional data imports (contacts via vCard/CSV, calendars via iCal/CalDAV, notes via Markdown, and preference questionnaires). All imported data flows through the same extraction pipeline and can be reviewed before confirmation.

---

## Observability

NeuroWeave exposes comprehensive observability through structured logs, Prometheus metrics, an append-only audit trail, and distributed tracing.

### Key Metrics (30+ total)

| Metric | Type | Description |
|--------|------|-------------|
| `em_extraction_latency_ms` | Histogram | Per-stage extraction latency |
| `em_entities_extracted` | Counter | Entities extracted by type and mechanism |
| `em_edges_created` / `em_edges_reinforced` | Counter | Graph mutation operations |
| `em_confidence_distribution` | Histogram | Current confidence distribution across edges |
| `em_probe_delivered` / `em_probe_accepted` | Counter | Probe delivery and engagement tracking |
| `em_hallucination_detected` | Counter | Blocked hallucinations by stage |
| `em_llm_tokens_used` | Counter | Token consumption per model per task |
| `em_circuit_breaker_state` | Gauge | Dependency health (0=closed, 1=half-open, 2=open) |

### Audit Trail

Every graph mutation and proactive decision is recorded in an append-only SQLite audit trail with 22 event types, correlation IDs for end-to-end tracing, and provenance metadata. The audit trail powers four debugging playbooks: "why did the agent know X?", "why didn't it know X?", "why was this probe delivered/not delivered?", and "extraction quality degraded".

### Alerting

10 pre-configured alerting rules covering extraction stalls, hallucination spikes, Neo4j degradation, LLM budget exhaustion, probe annoyance signals, and graph corruption detection.

---

## Testing

NeuroWeave uses a five-level testing pyramid:

| Level | What It Tests | Infrastructure |
|-------|--------------|----------------|
| **Unit** | Confidence formulas, hedge detection, temporal parsing, Cypher builders (~200 tests) | Pure Python, no dependencies |
| **Component** | Extraction pipeline, Graph Diff Engine, Proactive Engine in isolation with mocked LLMs | Mock LLM server, test fixtures |
| **Integration** | Full data flows: Agent → EM → Neo4j → Outbound Queue with real storage | Docker Compose (Neo4j, Redis, Qdrant, LLM mock) |
| **Scenario Simulation** | Multi-conversation scenarios with compressed timelines, 4 test personas, 50–100 interactions each | Scenario simulator with time warp |
| **Experience Quality** | LLM-as-judge A/B comparison: EM-enabled agent vs baseline on personalization, anticipation, consistency, naturalness, restraint | Evaluation harness |

### Running Tests

```bash
# Unit tests
pytest tests/unit -v

# Component tests (requires mock LLM server)
pytest tests/component -v

# Integration tests (requires Docker dependencies)
docker compose -f docker-compose.test.yml up -d
pytest tests/integration -v

# Scenario simulation
pytest tests/scenarios -v --persona alex_cto

# Full suite
make test
```

### Quality Targets

| Metric | Target |
|--------|--------|
| Extraction precision (facts stored are correct) | > 95% |
| Extraction recall (mentioned facts are captured) | > 85% |
| Confidence calibration error | < 0.10 |
| False positive rate (wrong facts at high confidence) | < 2% |
| Probe relevance (appropriate timing and context) | > 80% |
| Contradiction handling (corrections properly applied) | 100% |

---

## Edge Case Handling

NeuroWeave includes explicit handling strategies for conversational challenges that trip up naive extraction systems:

- **Hypotheticals** — "If I were buying a car, I'd want a Tesla" is detected via conditional language and stored as a low-confidence interest signal, not a preference
- **Sarcasm** — "Oh great, another Monday meeting" triggers sentiment inversion with reduced confidence
- **Multi-person attribution** — "My wife likes red wine but my sister prefers white" uses syntactic proximity to correctly attribute each preference
- **Secondhand knowledge** — "My colleague John thinks React is best" is tagged as secondhand with reduced confidence
- **Retractions** — "Actually, forget what I said about that" immediately zeros confidence and marks as retracted
- **Code content** — Variable names and string literals in code blocks are not extracted as entities; only meta-intention is captured
- **Emotional venting** — High-emotion clusters are stored as episodes, not traits, with suppressed wish confidence

---

## Project Structure

```
neuroweave/
├── src/neuroweave/
│   ├── core/                  # Core domain models and graph schema
│   ├── extraction/            # Multi-stage extraction pipeline
│   │   ├── entity.py          # Entity extraction stage
│   │   ├── relation.py        # Relation extraction stage
│   │   ├── sentiment.py       # Sentiment and hedging detection
│   │   ├── temporal.py        # Temporal scope classification
│   │   ├── confidence.py      # Confidence scoring formula
│   │   └── repair.py          # LLM output repair utilities
│   ├── graph/                 # Graph Diff Engine and Neo4j operations
│   ├── proactive/             # Proactive Engine (probes, starters, triggers)
│   ├── inference/             # Inference Engine (cross-context patterns)
│   ├── workers/               # Background workers (revision, decay, events)
│   ├── mcp/                   # MCP tool server implementation
│   ├── grpc/                  # gRPC service definitions and handlers
│   ├── privacy/               # PII detection, classification, sharing
│   ├── observability/         # Metrics, audit trail, structured logging
│   └── config/                # Configuration schema and validation
├── tests/
│   ├── unit/
│   ├── component/
│   ├── integration/
│   ├── scenarios/
│   └── fixtures/              # Test corpus (100+ labeled examples)
├── config/
│   └── experience_memory.yaml
├── docs/
│   ├── architecture.md
│   ├── configuration.md
│   ├── integration.md
│   ├── api-reference.md
│   └── threat-model.md
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## Roadmap

- [x] Core graph model and schema design
- [x] Extraction pipeline architecture (7-stage)
- [x] Proactive engine with risk model
- [x] Privacy classification system (L0–L4)
- [x] GDPR compliance (access, rectification, erasure, portability)
- [x] Threat model and mitigation strategies
- [x] Configuration schema (80+ knobs, 3 proactivity presets)
- [x] Testing strategy (5-level pyramid, 4 test personas)
- [x] Observability design (30+ metrics, 22 audit event types, 10 alert rules)
- [ ] Core implementation (extraction pipeline, graph diff engine)
- [ ] MCP server implementation
- [ ] Background worker implementation
- [ ] Experience sharing protocol
- [ ] Control UI graph visualizer
- [ ] Studio workflow trigger integration
- [ ] Voice pipeline STT confidence integration
- [ ] Federated experience aggregation

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup

```bash
git clone https://github.com/user/neuroweave.git
cd neuroweave
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
docker compose up -d   # Start Neo4j, Redis, Qdrant
make test              # Verify everything works
```

### Areas We Need Help

- **Extraction pipeline tuning** — Improving entity/relation extraction accuracy across diverse conversation styles
- **Inference engine** — Multi-hop graph reasoning and pattern discovery algorithms
- **Privacy** — Differential privacy implementation for experience sharing
- **Language support** — Extending extraction and probing to non-English languages
- **Benchmarks** — Building comprehensive evaluation datasets for agent memory systems

---

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture Overview](docs/architecture.md) | System topology, data flows, component interactions |
| [Experience Memory Deep Dive](docs/experience-memory.md) | Core concepts, graph model, acquisition patterns |
| [Integration Guide](docs/integration.md) | 7 integration surfaces, failure modes, fallbacks |
| [Configuration Reference](docs/configuration.md) | All 80+ config knobs with defaults and validation rules |
| [API Reference](docs/api-reference.md) | MCP tools, gRPC protos, extraction prompts |
| [Threat Model](docs/threat-model.md) | 6 threat categories, mitigations, GDPR compliance |
| [Testing Guide](docs/testing.md) | 5-level testing pyramid, scenario simulator, evaluation metrics |
| [Observability](docs/observability.md) | Metrics, audit trail, debugging playbooks, alerting rules |

---

## License

[Apache 2.0](LICENSE)

---

<p align="center">
  <strong>NeuroWeave</strong> — Agents that learn. Memory that compounds. Privacy that's provable.
</p>
