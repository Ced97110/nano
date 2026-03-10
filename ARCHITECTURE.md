# Nano Bana Pro -- Backend Architecture Guide

> **Audience:** Junior developers joining the team who need to understand the system well enough to contribute code.
>
> **Last updated:** March 2026

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Project Structure](#2-project-structure)
3. [The Agent System (DEEP DIVE)](#3-the-agent-system-deep-dive)
4. [The Pipeline System (DEEP DIVE)](#4-the-pipeline-system-deep-dive)
5. [The FinAgent System](#5-the-finagent-system)
6. [The Audit System](#6-the-audit-system)
7. [The Orchestrator & DI Container](#7-the-orchestrator--di-container)
8. [The API Layer](#8-the-api-layer)
9. [Infrastructure Adapters](#9-infrastructure-adapters)
10. [Data Flow (End-to-End)](#10-data-flow-end-to-end)

---

## 1. High-Level Overview

### What Is This Backend?

This is the backend for **Nano Bana Pro**, a "Contextual Intelligence" platform that correlates capital allocation with geopolitical stability. The backend's primary job today is running a **27-agent financial analysis pipeline** that produces investment-grade dossiers for any publicly traded company.

When a user says "Analyze TSLA," the backend:
1. Fetches real financial data from Yahoo Finance and SEC EDGAR
2. Orchestrates 27 specialized AI agents organized into 8 parallel execution waves
3. Audits every agent's output for hallucinations, inconsistencies, and completeness
4. Assembles a structured investment dossier with executive summary, valuation, risk assessment, and IC memo
5. Streams progress events to the frontend in real-time via SSE

### Architecture Diagram

```
                          +---------------------------+
                          |     Next.js Frontend      |
                          +---------------------------+
                                     |
                          HTTP (REST + SSE streaming)
                                     |
                          +---------------------------+
                          |     FastAPI (main.py)     |
                          |  CORS, Auth, Routing      |
                          +---------------------------+
                                     |
               +---------------------+---------------------+
               |                     |                     |
    +----------v------+   +---------v--------+   +--------v--------+
    | analysis_ctrl   |   | documents_ctrl   |   | ingestion_ctrl  |
    | export_ctrl     |   |                  |   |                 |
    | auth_ctrl       |   |                  |   |                 |
    +---------+-------+   +--------+---------+   +--------+--------+
              |                    |                       |
    +---------v-------------------v-----------------------v--------+
    |                    APPLICATION LAYER                          |
    |  RunAnalysisUseCase    StreamAnalysisUseCase                 |
    |  CompanyDataService    RAGService    DataIngestionService    |
    +------------------------------+-------------------------------+
                                   |
                    +--------------v--------------+
                    |      CORE / DOMAIN          |
                    |  Orchestrator -> FinAgentPro |
                    |  BasePersonaSystem           |
                    |  BaseAgent (x27 agents)      |
                    |  4-Layer Audit System        |
                    |  DCF domain service          |
                    +-----+----+----+----+--------+
                          |    |    |    |
           +--------------+    |    |    +---------------+
           |              +----+    +------+             |
    +------v------+ +-----v-----+ +--------v---+ +------v------+
    | OpenAI GW   | | Redis     | | PostgreSQL | | ChromaDB    |
    | (LLM calls) | | (cache +  | | (company   | | (RAG vector |
    |             | |  events + | |  data +    | |  store)     |
    |             | |  HITL)    | |  audit)    | |             |
    +------+------+ +-----------+ +------+-----+ +-------------+
           |                             |
    +------v------+               +------v------+
    | OpenAI API  |               | yfinance    |
    | (or Ollama) |               | SEC EDGAR   |
    +-------------+               | Tavily      |
                                  +-------------+
```

### Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Web framework** | FastAPI | REST API + SSE streaming |
| **Agent orchestration** | LangGraph | DAG-based parallel agent execution |
| **LLM gateway** | OpenAI API (via aiohttp) | Chat completions (works with Ollama too) |
| **Token counting** | tiktoken | Precise token counts for cost tracking |
| **Structured output** | Pydantic | Schema validation for LLM responses |
| **Database** | PostgreSQL (asyncpg) | Company data cache + audit trail |
| **Cache / Events** | Redis (redis.asyncio) | Agent caching, SSE pub/sub, HITL sync |
| **Vector store** | ChromaDB | RAG retrieval for SEC filings |
| **Market data** | yfinance | Real-time stock prices, financials, news |
| **SEC filings** | edgartools | 10-K, 10-Q, proxy statement access |
| **Web search** | Tavily | Real-time web/news search for agents |
| **Auth** | Clerk (RS256 JWKS) or self-signed HS256 JWT | RBAC with viewer/analyst/admin roles |
| **Logging** | structlog | Structured JSON logging throughout |
| **Export** | openpyxl, python-pptx | XLSX and PPTX dossier export |

---

## 2. Project Structure

```
backend/
  app/
    main.py                          # FastAPI entry point, wires DI container
    core/
      container.py                   # DI composition root
      orchestrator.py                # Routes requests to persona systems
      cross_system_registry.py       # Future: cross-system data sharing
    domain/
      entities/
        analysis.py                  # AnalysisRequest, AnalysisResult
        agent_output.py              # AgentOutput dataclass
      interfaces/                    # Abstract ports (ABCs)
        llm_gateway.py               # LLMGateway ABC
        cache_repository.py          # CacheRepository ABC
        event_publisher.py           # EventPublisher ABC
        audit_store.py               # AuditStore ABC + AuditEvent
        document_store.py            # DocumentStore ABC + Document
        market_data_repository.py    # MarketDataRepository ABC
        financial_data_repository.py # FinancialDataRepository ABC
        company_data_store.py        # CompanyDataStore ABC
        web_search.py                # WebSearchGateway ABC
      models/
        provenance.py                # DataSource, ProvenanceRecord
      services/
        dcf.py                       # Pure-math DCF computation
      value_objects/
        risk.py                      # RiskTier enum
    application/
      dto/
        analysis_dto.py              # AnalysisRequestDTO, AnalysisResultDTO
      use_cases/
        run_analysis.py              # Synchronous analysis use case
        stream_analysis.py           # SSE-streaming analysis use case
      services/
        company_data_service.py      # DB-backed fetch-through cache
        rag_service.py               # SEC filing ingestion + RAG retrieval
        data_ingestion_service.py    # Pre-warm data for tickers
    persona_systems/
      base_agent.py                  # BaseAgent -- parent of all agents
      base_system.py                 # BasePersonaSystem -- LangGraph DAG engine
      audit/
        schemas.py                   # Layer 1: deterministic schema validation
        consistency.py               # Layer 2: cross-agent consistency checks
        llm_audit.py                 # Layer 3: LLM audit + Layer 4: adversarial
        cost_monitor.py              # Budget enforcement + cost tracking
      finagent/
        system.py                    # FinAgentPro -- 27-agent pipeline
        agents/
          a0_company_profile.py      # through a26_sensitivity.py (27 agents)
    infrastructure/
      config.py                      # Settings (pydantic-settings, reads .env)
      llm/
        openai_gateway.py            # OpenAI-compatible LLM adapter (aiohttp)
        anthropic_gateway.py         # Anthropic adapter (unused currently)
      persistence/
        redis_cache_repository.py    # Redis cache adapter
        postgres_audit_store.py      # Immutable audit trail (INSERT-only)
        postgres_company_store.py    # Company data CRUD
        chroma_document_store.py     # ChromaDB RAG adapter
      messaging/
        redis_event_publisher.py     # Redis pub/sub + BLPOP/RPUSH for HITL
      data/
        yfinance_repository.py       # Yahoo Finance market data
        sec_edgar_repository.py      # SEC EDGAR filings
      web/
        tavily_search.py             # Tavily web search
        null_search.py               # No-op fallback
      export/
        xlsx_generator.py            # XLSX dossier export
        pptx_generator.py            # PPTX dossier export
      parsers/
        document_parser.py           # PDF/DOCX/TXT parser for uploads
    interface/
      auth.py                        # JWT auth (Clerk JWKS or legacy HS256)
      api/v1/
        analysis_controller.py       # /api/v1/analysis/* endpoints
        documents_controller.py      # /api/v1/documents/* endpoints
        ingestion_controller.py      # /api/v1/ingestion/* endpoints
        export_controller.py         # /api/v1/export/* endpoints
        auth_controller.py           # /api/v1/auth/* endpoints
        schemas.py                   # Pydantic request/response schemas
  db/
    init.sql                         # PostgreSQL schema (6 tables)
  requirements.txt                   # Python dependencies
  Dockerfile                         # Container build
  docker-compose.yml                 # Local dev (Postgres + Redis)
```

### Clean Architecture Layers

The codebase follows **Clean Architecture** with strict dependency rules:

```
  DOMAIN (innermost -- zero external deps)
    |
  APPLICATION (use cases, services -- depends only on domain)
    |
  INFRASTRUCTURE (adapters -- implements domain interfaces)
    |
  INTERFACE (controllers -- thin HTTP adapters)
    |
  CORE (wiring -- the only place that touches all layers)
```

**The rule:** Dependencies point inward. Domain never imports from infrastructure. Infrastructure implements domain interfaces (ports). Only `main.py` and `container.py` touch both layers.

For example, `BaseAgent` depends on `LLMGateway` (a domain ABC), not on `OpenAIGateway` (an infrastructure class). The container wires the concrete to the abstract at startup.

---

## 3. The Agent System (DEEP DIVE)

### What Is an Agent?

An **agent** is a single unit of analysis within the pipeline. Each agent:
- Has a specific analytical responsibility (e.g., "parse financial statements" or "build a DCF model")
- Receives the full pipeline state as input
- Calls an LLM with a carefully crafted system prompt
- Returns structured JSON output
- Tracks its own cost, latency, tokens, and data provenance

Every agent is a Python class that extends `BaseAgent` (defined in `app/persona_systems/base_agent.py`).

### How Agents Are Defined

Here is the anatomy of an agent class, using A0 (Company Profile) as an example:

```python
class CompanyProfileAgent(BaseAgent):
    # ---- Identity ----
    agent_id = "finagent.A0_company_profile"  # Unique ID, used as key in state dict
    persona_system = "finagent"                # Which system owns this agent

    # ---- LLM Configuration ----
    temperature = 0.2        # Low temperature for factual data
    max_tokens = 1500        # Max response tokens
    timeout_seconds = 90     # Execution timeout (asyncio.wait_for)

    # ---- System Prompt ----
    system_prompt = """You are a Senior Equity Research Associate...
    Output valid JSON:
    {
        "company_name": "...",
        "ticker": "...",
        ...
    }"""

    # ---- The Core Logic ----
    async def execute(self, state: dict) -> AgentOutput:
        entity = state.get("entity", "UNKNOWN")

        # 1. Fetch real data from the database (pre-ingested)
        svc = self._data.get("company_data")
        real_data = await svc._store.get_profile(entity)

        # 2. Build prompt with real data context
        prompt = f"Here is REAL company data for {entity}:\n{json.dumps(real_data)}\n..."

        # 3. Call the LLM
        result = await self.call_llm([{"role": "user", "content": prompt}])

        # 4. Parse JSON from LLM response
        parsed = self.parse_json(result["content"])

        # 5. Return structured output
        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed,
            confidence_score=0.92,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=...,
            data_sources_accessed=["yahoo_finance"],
        )
```

Every agent follows this same pattern: fetch context -> build prompt -> call LLM -> parse response -> return AgentOutput.

### How Agents Call the LLM

`BaseAgent` provides two methods for LLM interaction:

#### `call_llm(messages, max_tokens=None, temperature=None) -> dict`

Sends raw messages to the LLM and returns the response as a dict:

```python
result = await self.call_llm(
    messages=[{"role": "user", "content": "Analyze TSLA..."}],
    max_tokens=2048,  # Optional override (defaults to agent's self.max_tokens)
)
# result = {"content": "...", "tokens_used": 1234, "cost_usd": 0.05, ...}
```

Under the hood, this delegates to `self._llm.chat()` -- the injected `LLMGateway` interface. The agent's `system_prompt` is automatically prepended. If the agent sets `model_override`, that model is used instead of the default.

#### `call_llm_structured(messages, response_model, ...) -> tuple[T, dict]`

Same as `call_llm` but also validates the response against a Pydantic model:

```python
class DCFAssumptions(BaseModel):
    wacc: float
    terminal_growth_rate: float
    projected_fcf: list[float]

assumptions, metadata = await self.call_llm_structured(
    messages=[...],
    response_model=DCFAssumptions,
)
# assumptions is a validated Pydantic model
# metadata has tokens_used, cost_usd, etc.
```

The gateway calls the LLM, strips markdown code fences from the response, parses the JSON, and validates it against the Pydantic schema. Retries up to `max_retries` times on parse failure.

### How Agents Get Their Input Data

Agents receive data from three sources:

**1. Pipeline state (outputs from prior agents):**
```python
# Get output from a specific earlier agent
financials = self.get_prior(state, "finagent.A1_financial_statements")
# Returns {} if that agent hasn't run yet or errored
```

**2. Database (pre-ingested market data):**
```python
svc = self._data.get("company_data")  # CompanyDataService
profile = await svc._store.get_profile(entity)
```

**3. Web search (real-time context):**
```python
results = await self.search_web("TSLA investment thesis analyst rating 2025")
# Returns list of {title, url, content, score}
```

**4. RAG retrieval (SEC filings):**
```python
rag = self._data.get("rag")
risk_factors = await rag.get_risk_factors("TSLA", "What are the key risk factors?")
```

**5. Cross-system context (future -- data from other persona systems):**
```python
crip_data = self.get_cross_system_data(state, "crip")
```

### How Agents Return Structured Output

Every agent's `execute()` must return an `AgentOutput` dataclass:

```python
@dataclass
class AgentOutput:
    agent_id: str                                    # e.g., "finagent.A10_dcf"
    output: dict                                     # The actual JSON output
    confidence_score: float = 0.0                    # 0.0 to 1.0
    tokens_used: int = 0                             # Total tokens consumed
    cost_usd: float = 0.0                            # Estimated USD cost
    latency_ms: int = 0                              # Wall-clock execution time
    data_sources_accessed: list[str] = []            # ["yahoo_finance", "web_search"]
    error: str | None = None                         # Error message if failed
    provenance: dict[str, list[dict]] | None = None  # Per-field source tracking
```

The `BaseAgent.__call__` method wraps `execute()` and:
1. Checks the agent-level cache (keyed by agent_id + entity + intent hash)
2. Runs `execute()` with a timeout (`asyncio.wait_for`)
3. Publishes SSE events (AGENT_STATE_STARTED, AGENT_STATE_COMPLETED)
4. Logs audit events (agent_started, agent_completed, agent_error)
5. Caches the result for future calls
6. Returns the output in the format LangGraph expects: `{"agent_outputs": {agent_id: output}, "cost_log": {...}}`

### Agent Schemas and JSON Parsing

LLM responses are almost always JSON, but LLMs sometimes wrap JSON in markdown fences or prose. `BaseAgent.parse_json()` handles this robustly:

1. Strips ```json ... ``` fences
2. Tries `json.loads()`
3. If that fails, extracts the first balanced `{...}` or `[...]` from the text
4. If all else fails, returns `{"raw": original_text}`

The audit system's Layer 1 (schema validation) then checks whether the parsed output has the required keys. See [Section 6](#6-the-audit-system) for details.

### Provenance Tracking

Agents can track where each piece of data came from:

```python
self.track_provenance(
    field_path="revenue_growth",    # Which output field
    value="15.3%",                  # The value
    source_type="yfinance",         # Where it came from
    source_id="yahoo_finance_api",  # Specific source
    confidence=0.95,                # How confident we are
)

# For web search results:
self.track_web_provenance("investment_thesis", entity, web_results)
```

Provenance is attached to the agent output and flows through to the final dossier, enabling "show your sources" in the frontend.

---

## 4. The Pipeline System (DEEP DIVE)

### What Is a Pipeline/Persona System?

A **persona system** is a complete analysis pipeline that orchestrates multiple agents. `BasePersonaSystem` (in `app/persona_systems/base_system.py`) is the base class that provides the LangGraph execution engine.

Currently there is one persona system: **FinAgentPro** (27 agents for financial analysis). The architecture supports adding more (e.g., a country risk system, a competitive strategy system).

### How the LangGraph StateGraph Is Built

LangGraph is a framework for building stateful, graph-based agent workflows. Here's how we use it:

**Step 1: Define the state schema**

```python
class PipelineState(TypedDict):
    intent: dict                                      # User's query/ticker
    request: dict                                     # Request metadata
    cross_system_context: dict                        # Data from other systems
    agent_outputs: Annotated[dict, _merge_dicts]      # All agent outputs (merged)
    request_id: str                                   # Unique run ID
    entity: str                                       # e.g., "TSLA"
    audit_log: Annotated[dict, _merge_dicts]          # Audit findings per wave
    cost_log: Annotated[dict, _merge_dicts]           # Cost tracking per agent
    hitl_mode: str                                    # "express" | "analyst" | "review"
```

The `Annotated[dict, _merge_dicts]` tells LangGraph how to combine outputs from parallel nodes: merge dicts instead of overwriting. This is critical because agents in the same wave run in parallel and each returns `{"agent_outputs": {their_id: their_output}}` -- these get merged into a single dict.

**Step 2: Compute execution waves from the dependency graph**

The `_compute_waves()` method takes the dependency graph (a dict of `agent_id -> [dependency_ids]`) and produces a topologically-sorted list of waves:

```python
# Input: dependency graph
{
    "A0": [],           # No dependencies -> Wave 0
    "A1": [],           # No dependencies -> Wave 0
    "A5": ["A0", "A1"], # Depends on Wave 0 agents -> Wave 1
    "A10": ["A5"],      # Depends on Wave 1 agents -> Wave 2
}

# Output: waves
[
    ["A0", "A1"],  # Wave 0: run in parallel
    ["A5"],        # Wave 1: run after Wave 0 completes
    ["A10"],       # Wave 2: run after Wave 1 completes
]
```

**Step 3: Build the StateGraph**

```
START ──> [A0, A1, A2, A3, A4]  ──> _barrier_0 ──> [A5, A6, A7, A8, A9] ──> _barrier_1 ──> ... ──> END
          ^--- Wave 0 (parallel) ---^               ^--- Wave 1 (parallel) ---^
```

Each agent is added as a node. Agents in the same wave all have edges from START (for Wave 0) or from the previous barrier. All agents in a wave have edges TO the next barrier (or to END for the last wave).

The barrier nodes (`_barrier_0`, `_barrier_1`, etc.) are validator functions that run the audit system between waves.

**Step 4: Compile and cache the graph**

```python
self._compiled_graph = builder.compile()
```

The compiled graph is cached per `analysis_type` so repeated runs with the same configuration don't recompile.

### Wave-Based Execution

The wave structure means:
- **Within a wave:** All agents run in parallel (LangGraph handles this via asyncio)
- **Between waves:** A barrier node runs audit checks, then the next wave starts
- **Dependencies are guaranteed:** An agent only runs after ALL its dependencies have completed

This gives us **maximum parallelism** within the constraint of data dependencies. A full 27-agent run takes ~8 sequential wave steps, not 27 sequential agent steps.

### How State Flows Between Agents

When an agent completes, it returns:
```python
{
    "agent_outputs": {"finagent.A1_financial_statements": {...the output...}},
    "cost_log": {"finagent.A1_financial_statements": {"tokens_used": 1234, ...}},
}
```

LangGraph's `_merge_dicts` reducer merges this into the global state. So after Wave 0 completes, `state["agent_outputs"]` contains outputs from all 5 Wave 0 agents.

When a Wave 1 agent runs, it reads prior outputs via:
```python
financials = self.get_prior(state, "finagent.A1_financial_statements")
```

This is just a dict lookup: `state.get("agent_outputs", {}).get("finagent.A1_financial_statements", {})`.

### Graph Compilation and Caching

FinAgentPro supports multiple `analysis_type` values that filter which agents run:
- `"full"` -- all 27 agents
- `"quick"` -- 21 core agents (skips specialized Wave 6/7)
- `"ma_focused"` -- core + M&A analysis agent
- `"credit_focused"` -- core + LBO + credit analysis agents
- `"valuation_deep"` -- core + LBO + operating model + sensitivity

Each type produces a different DAG topology, so the compiled graph is cached per type:
```python
if analysis_type not in self._graph_cache:
    self._graph_cache[analysis_type] = self._compile_graph()
self._compiled_graph = self._graph_cache[analysis_type]
```

---

## 5. The FinAgent System

### All 27 Agents Listed with Purpose

| Agent | ID | Wave | Purpose |
|-------|----|------|---------|
| A0 Company Profile | `finagent.A0_company_profile` | 0 | Fetches/enriches company identity (name, sector, HQ, CEO, employees) |
| A1 Financial Statements | `finagent.A1_financial_statements` | 0 | Parses 3-statement model (income, balance sheet, cash flow) + key ratios |
| A2 Market Data | `finagent.A2_market_data` | 0 | Current price, market cap, PE ratio, beta, analyst targets |
| A3 Industry Context | `finagent.A3_industry_context` | 0 | Industry trends, competitive landscape, regulatory environment |
| A4 News & Sentiment | `finagent.A4_news_sentiment` | 0 | Recent news synthesis, sentiment scoring, event detection |
| A5 Revenue Model | `finagent.A5_revenue_model` | 1 | Revenue segmentation, growth drivers, geographic mix |
| A6 Profitability | `finagent.A6_profitability` | 1 | Margin analysis (gross, operating, net), cost structure |
| A7 Balance Sheet | `finagent.A7_balance_sheet` | 1 | Liquidity, leverage, capital structure, financial health rating |
| A8 Cash Flow | `finagent.A8_cash_flow` | 1 | FCF analysis, capex, working capital, cash conversion |
| A9 Growth Trajectory | `finagent.A9_growth_trajectory` | 1 | Historical growth rates, forward projections, growth quality |
| A10 DCF | `finagent.A10_dcf` | 2 | Discounted cash flow valuation with WACC, terminal value, sensitivity table |
| A11 Comps | `finagent.A11_comps` | 2 | Comparable company analysis (peer group, trading multiples) |
| A12 Precedent Transactions | `finagent.A12_precedent_transactions` | 2 | M&A transaction comps, implied valuations |
| A13 Sum of Parts | `finagent.A13_sum_of_parts` | 2 | Segment-level valuation, conglomerate discount analysis |
| A14 Risk Assessment | `finagent.A14_risk_assessment` | 3 | Multi-dimensional risk scoring (0-100), risk tier, risk matrix |
| A15 Management Quality | `finagent.A15_management_quality` | 3 | Leadership assessment, track record, compensation alignment |
| A16 ESG & Governance | `finagent.A16_esg_governance` | 3 | Environmental, social, governance scoring |
| A17 Competitive Moat | `finagent.A17_competitive_moat` | 3 | Moat width/source analysis (brand, network, cost, switching) |
| A18 Investment Thesis | `finagent.A18_investment_thesis` | 4 | Bull/base/bear synthesis, recommendation, target price |
| A19 Executive Summary | `finagent.A19_executive_summary` | 4 | Investor-facing summary with headline, SWOT, action items |
| A20 IC Memo | `finagent.A20_ic_memo` | 5 | Internal investment committee memorandum with dissenting view |
| A21 M&A Analysis | `finagent.A21_ma_analysis` | 6 | Acquisition target/acquirer analysis, strategic rationale |
| A22 LBO Model | `finagent.A22_lbo_model` | 6 | Leveraged buyout model, debt capacity, IRR analysis |
| A23 IPO Readiness | `finagent.A23_ipo_readiness` | 6 | IPO readiness assessment, comparables, pricing |
| A24 Credit Analysis | `finagent.A24_credit_analysis` | 6 | Credit rating estimation, debt covenants, recovery analysis |
| A25 Operating Model | `finagent.A25_operating_model` | 6 | Detailed operational KPIs, unit economics, scalability |
| A26 Sensitivity Analysis | `finagent.A26_sensitivity` | 7 | Multi-variable sensitivity across valuation methodologies |

### Wave Groupings

```
Wave 0 -- Data Gathering (5 agents, parallel)
  [A0, A1, A2, A3, A4]
  No dependencies. Fetch raw data from DB + LLM enrichment.
       |
  _barrier_0 (Layer 1+2+3 audit)
       |
Wave 1 -- Analysis (5 agents, parallel)
  [A5, A6, A7, A8, A9]
  Depend on all Wave 0 agents. Deep-dive into specific financial dimensions.
       |
  _barrier_1 (Layer 1+2+3 audit)
       |
Wave 2 -- Valuation (4 agents, parallel)
  [A10, A11, A12, A13]
  Depend on Wave 0+1. Four independent valuation methodologies.
       |
  _barrier_2 (Layer 1+2+3 audit)
       |
Wave 3 -- Risk & Quality (4 agents, parallel)
  [A14, A15, A16, A17]
  Depend on Wave 0+1+2. Risk and qualitative assessment.
       |
  _barrier_3 (Layer 1+2+3 audit)
       |
Wave 4 -- Synthesis (2 agents, parallel)
  [A18, A19]
  A18 (Thesis) reads from A0, A2, A5, A6, A8, A9, A10-A14, A17.
  A19 (Summary) reads from A0, A2, A14-A18.
       |
  _barrier_4
       |
Wave 5 -- IC Decision (1 agent)
  [A20]
  Reads from ALL prior agents. Produces the IC memo.
       |
  _barrier_5
       |
Wave 6 -- Specialized (5 agents, parallel)
  [A21, A22, A23, A24, A25]
  Optional: only run if analysis_type includes them.
       |
  _barrier_6
       |
Wave 7 -- Sensitivity (1 agent)
  [A26]
  Depends on A1, A2, A10, A11, A22, A25.
       |
  END
```

### Data Flow from Wave 0 to Wave 7

Here's how information cascades through the pipeline:

**Wave 0** produces the raw building blocks:
- A0: Company identity (name, sector, employees, executives)
- A1: Financial statements (revenue, net income, balance sheet, cash flow, ratios)
- A2: Market data (price, market cap, PE, beta, analyst targets)
- A3: Industry context (trends, competitors, regulatory landscape)
- A4: News (recent headlines, sentiment score)

**Wave 1** takes the raw data and performs focused analysis:
- A5 reads A0-A4 to decompose revenue into segments and forecast growth
- A6 reads A0-A4 to analyze margin structure and cost drivers
- A7 reads A0-A4 to assess balance sheet health and leverage
- A8 reads A0-A4 to analyze cash flow quality and working capital
- A9 reads A0-A4 to assess historical and projected growth rates

**Wave 2** uses everything above for valuation:
- A10 (DCF) reads A1, A2, A5-A9 to build a full DCF model with WACC via CAPM. Also calls `compute_dcf()` (a pure-math domain service) for deterministic calculation, then builds a sensitivity table.
- A11 (Comps) reads A0-A4, A5, A6 to find peer companies and compute relative valuation
- A12 (Precedent Txns) reads A0-A4, A5 for M&A transaction comparables
- A13 (SOTP) reads A0-A4, A5, A6 for sum-of-parts valuation

**Wave 3** assesses risk and quality:
- A14 (Risk) reads A0-A4, A7, A9, A10 to produce a 0-100 risk score with tier label
- A15 (Management) reads A0 for management quality assessment
- A16 (ESG) reads A0, A4 for ESG governance scoring
- A17 (Moat) reads A0-A4, A5, A6 for competitive moat analysis

**Wave 4** synthesizes everything:
- A18 (Thesis) reads 12 prior agents + web search to produce bull/base/bear cases
- A19 (Summary) reads A0, A2, A14-A18 for the investor-facing executive summary

**Wave 5** makes the final decision:
- A20 (IC Memo) reads all 20 prior agents, flags conflicts, writes the IC memo

**Waves 6-7** run specialized analyses that are only needed for certain analysis types.

### How the Final Dossier Is Assembled

After all waves complete, `FinAgentPro.run_pipeline()` assembles the result:

```python
result = {
    "type": "investment_dossier",
    "title": f"FinAgent Pro Analysis: {entity}",
    "entity": entity,
    "analysis_type": analysis_type,
    "content": {
        "executive_summary": outputs["finagent.A19_executive_summary"],
        "investment_thesis": outputs["finagent.A18_investment_thesis"],
        "ic_memo": outputs["finagent.A20_ic_memo"],
        "valuation": {
            "dcf": outputs["finagent.A10_dcf"],
            "comps": outputs["finagent.A11_comps"],
            ...
        },
        "fundamentals": { ... },
        "risk_and_quality": { ... },
        "specialized": { ... },  # Only present if those agents ran
    },
    "confidence_score": ...,  # Blended: 60% base + 40% adversarial review
    "audit": { ... },         # Full audit results
    "cost": { ... },          # Token/cost breakdown
}
```

---

## 6. The Audit System

The audit system has **4 layers** that progressively increase in sophistication. Layers 1-3 run at wave barriers; Layer 4 runs once at the very end.

### Layer 1: Schema Validation (Deterministic)

**File:** `app/persona_systems/audit/schemas.py`

Every agent has a schema of required output keys. For example:

```python
AGENT_SCHEMAS = {
    "finagent.A1_financial_statements": {
        "income_statement": dict,
        "balance_sheet": dict,
        "cash_flow": dict,
        "key_ratios": dict,
    },
    "finagent.A14_risk_assessment": {
        "overall_risk_score": None,  # None = any type, just check presence
        "risk_tier": str,
        "risk_dimensions": dict,
        "key_risks": list,
        "risk_matrix": dict,
    },
}
```

`validate_schema(agent_id, output)` checks:
- Is the output a dict? (not a string or error)
- Does it contain all required keys?
- Are the types correct?
- Is it unparsed raw text (JSON parsing failed)?

Returns a list of violation strings. Empty = passed.

### Layer 2: Cross-Agent Consistency (Deterministic)

**File:** `app/persona_systems/audit/consistency.py`

Compares outputs from different agents at each wave boundary to catch contradictions:

**After Wave 0:**
- P/S ratio sanity check (market_cap / revenue). Flags if > 200x or < 0.01x.
- Sector alignment between A0 (profile) and A3 (industry).

**After Wave 1:**
- Gross margin cross-check: computed from A1 financials vs. A6 profitability agent.
- Growth direction: A9 growth CAGR should directionally match A1 YoY growth.

**After Wave 2:**
- DCF vs. comps divergence: flags if they differ by more than 3x.
- Implied value vs. current price: flags if more than 5x or less than 0.1x.

**After Wave 3:**
- Risk vs. moat coherence: flags "CRITICAL risk + WIDE moat" or "STABLE risk + WEAK moat."
- Risk tier label matches score range (e.g., score 80 should be CRITICAL, not WATCH).

### Layer 3: LLM Audit (AI-Powered)

**File:** `app/persona_systems/audit/llm_audit.py`

Only runs on **critical-path agents** -- those with the highest blast radius:
- `A1` (Financial Statements) -- 15 downstream agents depend on it
- `A18` (Investment Thesis) -- feeds the executive summary and IC memo
- `A19` (Executive Summary) -- the final investor-facing output
- `A20` (IC Memo) -- the final IC decision document

A separate LLM call reviews the agent's output for:
1. **Hallucination:** Are specific numbers/names fabricated?
2. **Internal consistency:** Do the numbers add up?
3. **Reasonableness:** Are values in plausible ranges?
4. **Completeness:** Are critical fields missing?
5. **Contradictions:** Does the output contradict itself?

Returns a structured result with `passed`, `severity`, `issues`, and `confidence_adjustment` (a penalty from -0.3 to 0.0).

### Layer 4: Adversarial Review (AI-Powered)

Runs once after ALL agents complete (not at a barrier). This is the "devil's advocate" layer.

A senior LLM call (acting as an investment committee member) reviews the complete thesis, executive summary, and risk data to answer:
1. Is the recommendation supported by the data?
2. Are the bull/bear cases balanced or biased?
3. Are obvious risks being downplayed?
4. Is the target price derivation sound?
5. Would you present this to an investment committee?

Returns: `approved`, `overall_quality` ("publishable" / "needs_revision" / "unreliable"), `challenges`, `suggested_caveats`, and `final_confidence_score`.

The final dossier confidence is computed as:
```python
confidence = (base_confidence * 0.6) + (adversarial_confidence * 0.4)
```

Where `base_confidence` = (agents that succeeded without errors) / (total agents).

### How Audit Barriers Work Between Waves

In the LangGraph, barrier nodes are validator functions created by `_make_validator(wave_idx, wave_agent_ids)`. When a barrier runs:

1. **Layer 1:** Validate schema for each agent that just completed in this wave
2. **Layer 2:** Run cross-agent consistency checks for this wave
3. **Layer 3:** If any critical agents are in this wave, run LLM audit on them
4. **Store results:** Write audit findings to `state["audit_log"]`
5. **HITL check:** If the HITL mode requires a pause at this wave, wait for analyst feedback (see Section 8)

### Cost Monitoring and Loop Prevention

**File:** `app/persona_systems/audit/cost_monitor.py`

The `CostMonitor` class provides budget enforcement with these safeguards:

| Safeguard | Default | Purpose |
|-----------|---------|---------|
| `max_pipeline_cost_usd` | $2.00 | Hard cap on total pipeline spend |
| `max_agent_calls` | 3 | Max times any single agent can run (catches infinite loops) |
| `max_agent_latency_ms` | 60,000ms | Flags slow agents |
| `max_pipeline_duration_ms` | 300,000ms | 5-minute pipeline timeout |
| `max_total_tokens` | 500,000 | Hard cap on total token consumption |

Raises `BudgetExceededError` or `AgentLoopDetectedError` when limits are breached.

The cost monitor also includes a comprehensive `MODEL_PRICING` table for estimating costs across OpenAI, Anthropic, Google, and local models, and can generate ASCII cost reports.

> **Note:** The CostMonitor is currently defined but not yet integrated into the barrier nodes. The `run_pipeline()` method computes costs at the end from `cost_log` rather than enforcing budgets mid-pipeline. The integration guide in the file's docstring describes how to wire it in.

---

## 7. The Orchestrator & DI Container

### How container.py Wires Everything Together

`Container` is the **composition root** -- the only place where concrete infrastructure classes are imported and bound to abstract interfaces. Everything else depends on ports (ABCs).

The `Container.init()` method runs at startup and:

1. **Creates the LLM adapter:**
   ```python
   self.llm = OpenAIGateway(
       default_model=settings.llm_model,       # e.g., "gpt-4o"
       default_max_tokens=settings.llm_max_tokens,
       base_url=settings.openai_base_url,       # Custom URL for Ollama
   )
   ```

2. **Connects to Redis** (cache + events + HITL). Falls back to null objects if unavailable:
   ```python
   self.cache = RedisCacheRepository(self._redis)   # or _NullCache()
   self.events = RedisEventPublisher(self._redis)    # or _NullEvents()
   ```

3. **Connects to PostgreSQL** (company data + audit). Auto-runs `db/init.sql`:
   ```python
   self._pg_pool = await asyncpg.create_pool(settings.database_url, ...)
   self.audit_store = PostgresAuditStore(self._pg_pool)
   ```

4. **Creates data services:**
   ```python
   self.company_data = CompanyDataService(store, market_repo, filings_repo)
   self.rag = RAGService(doc_store, filings_repo)
   self.ingestion = DataIngestionService(company_data, rag)
   ```

5. **Creates the Orchestrator** (with all dependencies injected):
   ```python
   self.orchestrator = Orchestrator(
       llm=self.llm, cache=self.cache, events=self.events,
       data_repos=self.data_repos, audit_store=self.audit_store,
       web_search=self.web_search,
   )
   ```

6. **Creates use cases:**
   ```python
   self.run_analysis = RunAnalysisUseCase(self.orchestrator)
   self.stream_analysis = StreamAnalysisUseCase(self.orchestrator, self.events)
   ```

**Key design principle:** If a dependency is unavailable (Redis down, no Postgres), the container falls back to **null objects** that silently do nothing. The pipeline still runs -- it just won't have caching, events, or audit persistence. This means the system degrades gracefully.

### How the Orchestrator Routes Requests

The `Orchestrator` maps system IDs to persona system classes:

```python
PERSONA_SYSTEM_MAP = {
    "finagent": "app.persona_systems.finagent.system.FinAgentPro",
}
```

When `orchestrator.get_system("finagent")` is called:
1. It lazily imports and instantiates `FinAgentPro`
2. Passes all infrastructure dependencies (llm, cache, events, data_repos, audit_store, web_search)
3. Caches the instance for subsequent calls

### Lifecycle: init -> run -> shutdown

```python
# Startup (main.py lifespan)
await container.init()              # Connect to all external services
analysis_controller.configure(...)  # Inject use cases into controllers
# Optionally: pre-warm data
ingestion_task = asyncio.create_task(container.ingestion.ingest_watchlist(...))

# Running (handling requests)
result = await container.run_analysis.execute(dto)

# Shutdown
await container.shutdown()          # Close Redis, PostgreSQL connections
```

---

## 8. The API Layer

### Controllers and Endpoints

All endpoints live under `/api/v1/`. The controllers are thin adapters that validate input, delegate to use cases, and format output.

#### Analysis Endpoints (`analysis_controller.py`)

| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | `/api/v1/analysis/run` | analyst | Run analysis synchronously, return full dossier |
| POST | `/api/v1/analysis/run/stream` | analyst | Run analysis with SSE streaming |
| POST | `/api/v1/analysis/{request_id}/feedback` | analyst | Submit HITL feedback for a paused wave |
| GET | `/api/v1/analysis/systems` | viewer | List available persona systems |
| GET | `/api/v1/analysis/stats` | admin | Get LLM usage stats |
| GET | `/api/v1/analysis/{workflow_id}/audit` | analyst | Get full audit trail |
| GET | `/api/v1/analysis/{workflow_id}/compliance-report` | admin | Generate compliance report |
| POST | `/api/v1/analysis/{request_id}/approve-sharing` | analyst | Approve dossier for external sharing |
| GET | `/api/v1/analysis/{request_id}/sharing-status` | viewer | Check sharing approval status |

#### Other Endpoints

| Method | Path | Role | Description |
|--------|------|------|-------------|
| POST | `/api/v1/documents/upload` | analyst | Upload PDF/DOCX/TXT for RAG |
| GET | `/api/v1/documents/{document_id}` | viewer | Get document metadata |
| DELETE | `/api/v1/documents/{document_id}` | admin | Delete uploaded document |
| POST | `/api/v1/export/xlsx` | analyst | Export dossier as Excel |
| POST | `/api/v1/export/pptx` | analyst | Export dossier as PowerPoint |
| POST | `/api/v1/ingestion/ticker` | admin | Trigger data ingestion (async) |
| POST | `/api/v1/ingestion/ticker/sync` | admin | Trigger data ingestion (sync) |
| POST | `/api/v1/ingestion/watchlist` | admin | Ingest multiple tickers |
| GET | `/health` | public | Health check |

### SSE Streaming (How Events Flow from Pipeline to Browser)

The streaming endpoint (`POST /api/v1/analysis/run/stream`) returns a `text/event-stream` response. Here's the full flow:

**1. Frontend sends request:**
```
POST /api/v1/analysis/run/stream
{"persona_system": "finagent", "ticker": "TSLA", "mode": "express"}
```

**2. Backend creates the pipeline task and subscribes to events:**
```python
async def event_stream():
    # Start pipeline in background
    pipeline_task = asyncio.create_task(system.run_pipeline(...))

    # Subscribe to Redis pub/sub channel "analysis:{request_id}"
    async for event in self._events.subscribe(request_id):
        yield f"data: {json.dumps(event)}\n\n"
        if event.get("type") == "RUN_FINISHED":
            break

    # After RUN_FINISHED, yield the full result
    result = await pipeline_task
    yield f"data: {json.dumps({'type': 'RESULT', 'data': result})}\n\n"
```

**3. Events emitted during execution:**

```
data: {"type": "RUN_STARTED", "runId": "...", "total_agents": 27, "waves": 8}

data: {"type": "AGENT_STATE_STARTED", "agentId": "finagent.A0_company_profile"}
data: {"type": "AGENT_STATE_STARTED", "agentId": "finagent.A1_financial_statements"}
data: {"type": "AGENT_STATE_STARTED", "agentId": "finagent.A2_market_data"}
...
data: {"type": "AGENT_STATE_COMPLETED", "agentId": "finagent.A0_company_profile",
       "cached": false, "latency_ms": 2100, "tokens_used": 1234, "cost_usd": 0.03}
...

data: {"type": "WAVE_REVIEW", "wave": 0, "wave_label": "Data Gathering",
       "agent_outputs": {...}, "audit_findings": {...}}  // Only in analyst/review modes

data: {"type": "HUMAN_INPUT_RECEIVED", "wave": 0, "action": "approve"}  // After HITL

data: {"type": "RUN_FINISHED", "runId": "...", "confidence": 0.85,
       "total_tokens": 45000, "total_cost_usd": 0.95}

data: {"type": "RESULT", "data": {...full dossier...}}
```

The streaming use case also handles edge cases:
- If the pipeline crashes, it yields a `RUN_ERROR` event
- If the SSE connection drops, the pipeline task is cancelled
- It races `next_event_task` against `pipeline_task` using `asyncio.wait(FIRST_COMPLETED)` to detect pipeline crashes even when no events are being emitted

### Authentication (Clerk JWT)

**File:** `app/interface/auth.py`

Three auth modes, checked in order:

1. **Clerk mode** (production): If `CLERK_SECRET_KEY` is set, verify Clerk-issued JWTs via RS256 JWKS. The JWKS endpoint is fetched once and cached for 1 hour. User role comes from `publicMetadata.role` in the Clerk JWT.

2. **Legacy mode** (backwards compat): If `JWT_SECRET` is set, verify self-signed HS256 JWTs. Used for testing or standalone deployments.

3. **Dev mode** (local development): If neither key is set, all requests get admin access. No auth required.

**Role hierarchy:** `admin > analyst > viewer`
- **viewer:** Read-only (results, audit trails, sharing status)
- **analyst:** Run analyses, submit HITL feedback, approve sharing, upload documents
- **admin:** All analyst permissions + system stats + data ingestion + user management

### HITL (Human-in-the-Loop) Feedback Loop

HITL allows an analyst to review and override agent outputs mid-pipeline. Here's the full flow:

**1. User selects HITL mode when starting analysis:**
```json
{"mode": "analyst"}
```

**2. HITL gates determine which waves pause:**
```python
HITL_GATES = {
    "express": set(),         # No pauses
    "analyst": {0, 2},        # Pause after Data Gathering and Valuation
    "review":  {0, 1, 2, 3}, # Pause after every major wave
}
```

**3. At a gated barrier, the pipeline pauses:**
- Publishes a `WAVE_REVIEW` SSE event with the wave's agent outputs and audit findings
- Blocks on Redis `BLPOP("hitl:{request_id}:{wave}", timeout=300)`
- Waits up to 5 minutes for analyst feedback

**4. Analyst reviews in the frontend and submits feedback:**
```
POST /api/v1/analysis/{request_id}/feedback
{
    "wave": 0,
    "action": "approve",        // or "override", "reject", "cancel"
    "overrides": {},             // Agent output overrides (for "override" action)
    "notes": "Looks good"        // Optional analyst notes
}
```

This hits the feedback endpoint, which does:
```python
await self._events.send_input(f"{request_id}:{wave}", feedback_data)
# Internally: RPUSH("hitl:{request_id}:{wave}", json.dumps(feedback_data))
```

**5. Pipeline resumes:**
- **approve:** Continue as-is
- **override:** Merge `overrides` into `agent_outputs` via the `_merge_dicts` reducer. Downstream agents see the overrides when they call `get_prior()`.
- **reject:** Re-run all agents in this wave with analyst notes in state
- **cancel:** Abort the entire pipeline, emit `RUN_CANCELLED`
- **timeout (5 min):** Auto-continue

---

## 9. Infrastructure Adapters

### LLM Gateway (OpenAI-Compatible)

**File:** `app/infrastructure/llm/openai_gateway.py`

The `OpenAIGateway` is a lightweight adapter that calls any OpenAI-compatible API using `aiohttp` (not the openai SDK). This means it works with:
- **OpenAI API** (default: `https://api.openai.com/v1`)
- **Ollama** (set `OPENAI_BASE_URL=http://localhost:11434/v1`)
- **Any OpenAI-compatible provider** (Azure OpenAI, vLLM, etc.)

Key features:
- **Lazy imports:** tiktoken and aiohttp are only imported on first use, keeping server startup fast
- **Fallback models:** If the primary model fails, tries fallback models in sequence
- **Token counting:** Uses tiktoken for precise token counts; falls back to `len(text) // 4`
- **Cost estimation:** Maintains a `MODEL_COSTS` table and tracks running totals
- **Session reuse:** A single aiohttp session is reused across all calls

The `chat_structured()` method calls `chat()`, strips markdown code fences, parses JSON, and validates against a Pydantic model.

### PostgreSQL (Raw SQL via asyncpg)

**No ORM.** All SQL is hand-written and executed via asyncpg's connection pool.

**6 tables** defined in `db/init.sql`:

| Table | Purpose | Consumed by |
|-------|---------|-------------|
| `company_profiles` | Company identity data | A0 agent |
| `market_snapshots` | Current market data (price, PE, market cap) | A2 agent |
| `financial_statements` | Income/balance/cash flow per period | A1 agent |
| `company_news` | Recent news articles | A4 agent |
| `data_freshness` | Tracks when each data type was last fetched per ticker | CompanyDataService |
| `audit_trail` | Immutable append-only audit events | Compliance/audit endpoints |

The `audit_trail` table is **INSERT-only** -- UPDATE and DELETE are revoked at the database level. Minimum 7-year retention per compliance policy.

**Freshness tracking:** The `data_freshness` table stores `(ticker, data_type, last_fetched_at, stale_after_seconds, next_earnings_date)`. The `CompanyDataService` checks this before every data access and only re-fetches from Yahoo Finance if the data is stale.

| Data Type | Stale After | Notes |
|-----------|-------------|-------|
| profile | 7 days (604,800s) | Rarely changes |
| market | 15 minutes (900s) | Prices move intraday |
| financials | 1 day (86,400s) | Also re-fetches when `next_earnings_date` passes |
| news | 1 hour (3,600s) | News cycle |

### Redis (Cache + Events + HITL)

Redis serves three roles:

**1. Agent/Pipeline caching** (`RedisCacheRepository`):
```
agent:{agent_id}:{input_hash} -> JSON output  (TTL: 30 min)
pipeline:{system_id}:{entity} -> JSON dossier  (TTL: 1 hour)
```

**2. SSE event pub/sub** (`RedisEventPublisher`):
```
PUBLISH analysis:{request_id} {"type": "AGENT_STATE_COMPLETED", ...}
SUBSCRIBE analysis:{request_id}
```

**3. HITL synchronization** (reliable blocking):
```
# Pipeline barrier (waits):
BLPOP hitl:{request_id}:{wave} 300   # Block up to 5 min

# Analyst feedback (delivers):
RPUSH hitl:{request_id}:{wave} {"action": "approve"}
EXPIRE hitl:{request_id}:{wave} 600  # Cleanup after 10 min
```

Using `BLPOP/RPUSH` instead of pub/sub for HITL avoids race conditions -- the feedback is stored in a list and consumed exactly once.

### ChromaDB (RAG Vector Store)

**File:** `app/infrastructure/persistence/chroma_document_store.py`

Supports two modes:
- **Local:** `PersistentClient(path="./chroma_data")` -- filesystem storage
- **Cloud:** `CloudClient(api_key=..., tenant=..., database=...)` -- hosted ChromaDB

Uses the default `all-MiniLM-L6-v2` embedding model and cosine similarity.

**Collections:**
| Collection | Contents | Used by |
|------------|----------|---------|
| `sec_risk_factors` | 10-K Item 1A (Risk Factors) chunks | A14 (Risk Assessment) |
| `sec_mda` | 10-K Item 7 (MD&A) chunks | A3 (Industry), A12 (Precedent Txns) |
| `sec_proxy` | DEF 14A proxy statement chunks | A15 (Management Quality) |
| `industry_reports` | Industry analysis reports | A3 (Industry Context) |
| `user_uploads` | User-uploaded PDF/DOCX/TXT documents | Any agent (via RAG) |

Documents are chunked into 1,500-character segments with 200-character overlap, split on sentence boundaries.

### yfinance (Market Data)

**File:** `app/infrastructure/data/yfinance_repository.py`

Wraps the `yfinance` library to fetch:
- Company info (name, sector, HQ, employees, officers)
- Market data (price, market cap, PE, beta, 50+ fields)
- Financial statements (income, balance sheet, cash flow -- annual and quarterly)
- Price history (up to 252 trading days)
- News (up to 20 recent articles)

All yfinance calls run in a `ThreadPoolExecutor(max_workers=4)` via `loop.run_in_executor()` since yfinance is synchronous.

### SEC EDGAR (Financial Filings)

**File:** `app/infrastructure/data/sec_edgar_repository.py`

Uses the `edgartools` library to access:
- Company filings (10-K, 10-Q, DEF 14A) with accession numbers
- XBRL-extracted financial data (structured facts)
- Company facts (revenue, net income, assets, equity, EPS)

Sets the required SEC identity: `"NanoBana AI research@nanobana.com"`.

### Tavily (Web Search)

**File:** `app/infrastructure/web/tavily_search.py`

Provides real-time web and news search for agents. Features:
- **Rate limiting:** Async semaphore (max 5 concurrent requests)
- **Redis caching:** Results cached for 1 hour to avoid redundant API calls
- **Graceful degradation:** Returns empty list on any error

Used by agents like A18 (Investment Thesis) to get the latest analyst opinions and market developments.

---

## 10. Data Flow (End-to-End)

Here is exactly what happens when a user clicks "Analyze TSLA" in the frontend, step by step.

### Step 1: HTTP Request

The frontend sends:
```
POST /api/v1/analysis/run/stream
Authorization: Bearer <clerk_jwt>
Content-Type: application/json

{
    "persona_system": "finagent",
    "ticker": "TSLA",
    "mode": "express",
    "analysis_type": "full"
}
```

### Step 2: Authentication

`auth.py` extracts the JWT, fetches Clerk's JWKS (cached 1 hour), verifies the RS256 signature, extracts `sub` (user_id) and `publicMetadata.role`. The `require_role(Role.analyst)` dependency ensures the user has at least analyst access.

### Step 3: Controller Validates and Delegates

`analysis_controller.py`:
- Validates `persona_system` is in `{"finagent"}`
- Validates `mode` is in `{"express", "analyst", "review"}`
- Validates `analysis_type` is in `{"full", "quick", "ma_focused", "credit_focused", "valuation_deep"}`
- Creates an `AnalysisRequestDTO`
- Calls `_stream_use_case.execute(dto)`

### Step 4: StreamAnalysisUseCase

`stream_analysis.py`:
- Generates a UUID `request_id`
- Creates an `AnalysisRequest` domain entity (which computes `intent`)
- Gets the persona system: `orchestrator.get_system("finagent")` -> `FinAgentPro` instance
- Returns `(request_id, event_stream_generator)`

The controller wraps the generator in a `StreamingResponse(media_type="text/event-stream")`.

### Step 5: Pipeline Execution Starts

Inside the event stream generator, `system.run_pipeline()` is launched as an `asyncio.create_task()`. Simultaneously, the generator subscribes to Redis pub/sub on `analysis:{request_id}`.

### Step 6: FinAgentPro.run_pipeline()

1. **Entity extraction:** Extracts "TSLA" from the intent
2. **Dynamic DAG:** Sets `_active_agent_filter` based on `analysis_type` (for "full", all 27 agents)
3. **Cache check:** Checks Redis for `pipeline:finagent:TSLA`. If hit, returns cached result immediately.
4. **Background ingestion:** Fires `asyncio.create_task(ingestion_svc.ingest_ticker_background("TSLA"))` to ensure data is ready for next run
5. **Publish RUN_STARTED** event (SSE)
6. **Log audit event:** `run_started` to PostgreSQL
7. **Compile/cache the LangGraph** for this analysis_type
8. **Execute the DAG:** `await self.execute_dag_with_audit(initial_state)`

### Step 7: Wave 0 Execution (5 Agents in Parallel)

LangGraph starts executing A0, A1, A2, A3, A4 simultaneously.

For each agent (e.g., A1 Financial Statements):
1. `BaseAgent.__call__()` is invoked by LangGraph
2. Publishes `AGENT_STATE_STARTED` SSE event
3. Logs `agent_started` audit event
4. Computes input hash and checks agent cache
5. Calls `execute()` with timeout enforcement
6. `A1.execute()` reads from PostgreSQL (`store.get_financial_statements("TSLA")`)
7. Builds a prompt with the real financial data
8. Calls `self.call_llm(messages)` -> `OpenAIGateway.chat()` -> aiohttp POST to OpenAI
9. Parses the JSON response
10. Returns `AgentOutput(output={...}, tokens_used=1234, cost_usd=0.05, ...)`
11. `BaseAgent.__call__()` caches the result, publishes `AGENT_STATE_COMPLETED`, logs audit event
12. Returns `{"agent_outputs": {"finagent.A1_financial_statements": {...}}, "cost_log": {...}}`

LangGraph merges all 5 agents' outputs into the state dict.

### Step 8: Barrier 0 (Audit)

The `_barrier_0` validator node runs:
1. **Layer 1:** Checks A0-A4 outputs against their schemas
2. **Layer 2:** Runs `_check_wave0_consistency()` (P/S ratio sanity, sector alignment)
3. **Layer 3:** A1 is a critical agent -> LLM audit call checks for hallucinated numbers
4. Stores findings in `state["audit_log"]["wave_0"]`
5. Since mode is "express", no HITL pause

### Steps 9-15: Waves 1-7

Same pattern repeats for each wave. Each wave's agents read prior outputs via `self.get_prior(state, "finagent.A1_financial_statements")`.

Notable details:
- **A10 (DCF)** calls the deterministic `compute_dcf()` domain service after the LLM provides assumptions, then builds a sensitivity table
- **A18 (Investment Thesis)** calls `search_web()` to get latest analyst opinions
- **A20 (IC Memo)** reads ALL 20 prior agent outputs and explicitly flags conflicting signals

### Step 16: Layer 4 Adversarial Review

After all waves complete, `run_pipeline()` runs `adversarial_review()`:
- Takes the thesis (A18), summary (A19), risk data (A14), market data (A2), and all consistency warnings
- Makes one LLM call acting as a "senior investment committee member"
- Returns approval status, quality rating, challenges, and confidence score

### Step 17: Dossier Assembly

`run_pipeline()` assembles the final result dict with:
- All agent outputs organized by category (fundamentals, valuation, risk, etc.)
- Confidence score (60% base + 40% adversarial)
- Full audit log (wave audits + adversarial review)
- Cost breakdown (per-agent tokens and cost)

### Step 18: Cache and Publish

1. **Cache:** Store result in Redis as `pipeline:finagent:TSLA` (TTL 1 hour)
2. **Publish RUN_FINISHED** SSE event with confidence, token count, cost
3. **Log audit event:** `run_finished` to PostgreSQL

### Step 19: Final SSE Events

The event stream generator yields:
```
data: {"type": "RUN_FINISHED", "runId": "...", "confidence": 0.85, ...}
data: {"type": "RESULT", "data": {...the full dossier...}}
```

### Step 20: Frontend Receives Result

The frontend's EventSource receives the streamed events, shows agent progress in real-time, and renders the full dossier when the RESULT event arrives.

---

## Appendix: Key File Paths

For quick reference, here are the absolute paths to every key file discussed in this document:

| File | Purpose |
|------|---------|
| `/Users/ced/Desktop/nanoai/backend/app/main.py` | FastAPI entry point |
| `/Users/ced/Desktop/nanoai/backend/app/core/container.py` | DI composition root |
| `/Users/ced/Desktop/nanoai/backend/app/core/orchestrator.py` | Persona system router |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/base_agent.py` | Base class for all agents |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/base_system.py` | LangGraph DAG engine |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/finagent/system.py` | 27-agent pipeline |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/finagent/agents/` | All 27 agent files |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/audit/schemas.py` | Layer 1 schema validation |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/audit/consistency.py` | Layer 2 consistency checks |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/audit/llm_audit.py` | Layer 3+4 LLM audit |
| `/Users/ced/Desktop/nanoai/backend/app/persona_systems/audit/cost_monitor.py` | Budget enforcement |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/llm/openai_gateway.py` | LLM adapter |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/messaging/redis_event_publisher.py` | SSE + HITL |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/persistence/postgres_audit_store.py` | Audit trail |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/persistence/postgres_company_store.py` | Company data |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/persistence/chroma_document_store.py` | RAG store |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/data/yfinance_repository.py` | Market data |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/data/sec_edgar_repository.py` | SEC filings |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/web/tavily_search.py` | Web search |
| `/Users/ced/Desktop/nanoai/backend/app/application/services/company_data_service.py` | Fetch-through cache |
| `/Users/ced/Desktop/nanoai/backend/app/application/services/rag_service.py` | RAG ingestion/retrieval |
| `/Users/ced/Desktop/nanoai/backend/app/application/services/data_ingestion_service.py` | Startup data warming |
| `/Users/ced/Desktop/nanoai/backend/app/application/use_cases/stream_analysis.py` | SSE streaming use case |
| `/Users/ced/Desktop/nanoai/backend/app/interface/api/v1/analysis_controller.py` | Analysis endpoints |
| `/Users/ced/Desktop/nanoai/backend/app/interface/auth.py` | JWT auth (Clerk/legacy/dev) |
| `/Users/ced/Desktop/nanoai/backend/db/init.sql` | PostgreSQL schema |
| `/Users/ced/Desktop/nanoai/backend/app/infrastructure/config.py` | Environment settings |
| `/Users/ced/Desktop/nanoai/backend/app/domain/entities/agent_output.py` | AgentOutput dataclass |
| `/Users/ced/Desktop/nanoai/backend/app/domain/services/dcf.py` | DCF math (pure functions) |
| `/Users/ced/Desktop/nanoai/backend/app/domain/models/provenance.py` | Data provenance tracking |
