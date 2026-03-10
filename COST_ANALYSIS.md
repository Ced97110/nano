# Nano Bana Pro — Production Cost Analysis

> Generated: 2026-03-09 | Based on actual codebase audit of 27-agent FinAgentPro pipeline

---

## 1. Pipeline Token Budget (Per Full Analysis Run)

| Component | Tokens (input) | Tokens (output) | Total |
|-----------|---------------|-----------------|-------|
| 27 agents × ~2,000 in + ~1,500 out | ~54,000 | ~40,500 | ~94,500 |
| Layer 3 audit (4 critical agents) | ~8,000 | ~4,000 | ~12,000 |
| Layer 4 adversarial review | ~3,000 | ~1,500 | ~4,500 |
| **Total per full run (cold)** | **~65,000** | **~46,000** | **~111,000** |

Cache hits (30min agent TTL, 1hr pipeline TTL) reduce repeat queries by ~60-80%.

### Agent Configuration
- Default `max_tokens`: 2,048 per agent (global config: 4,096)
- Temperature: 0.3
- Per-agent timeout: 120s
- Embedding model: all-MiniLM-L6-v2 (ChromaDB default)
- RAG retrieval: 5 chunks per query, 1,500 chars/chunk

---

## 2. LLM Cost Per Run by Model

| Model | Input $/1M | Output $/1M | Cost/Run (cold) | Cost/Run (cached ~70%) |
|-------|-----------|-------------|-----------------|----------------------|
| **gpt-4o** | $2.50 | $10.00 | **$0.62** | **$0.19** |
| gpt-4o-mini | $0.15 | $0.60 | **$0.04** | **$0.01** |
| o3-mini | $1.10 | $4.40 | **$0.27** | **$0.08** |
| claude-sonnet-4 | $3.00 | $15.00 | **$0.89** | **$0.27** |
| claude-haiku-3.5 | $0.80 | $4.00 | **$0.24** | **$0.07** |
| glm-4.7 (Ollama) | $0.00 | $0.00 | **$0.00** | **$0.00** |

---

## 3. DAU / RPS / Monthly Projections

### Assumptions
- Average user runs **2 analyses/day**
- "Quick" mode (21 agents) used 60% of the time → ~0.75× token multiplier
- Peak RPS = 3× average (concentrated during market hours)
- Cache hit rate ~70% at scale (popular tickers queried repeatedly)

| DAU | Analyses/day | Avg Tokens/day | Peak RPS | Monthly Analyses |
|-----|-------------|---------------|----------|-----------------|
| 100 | 200 | 16.7M | 0.02 | 6,000 |
| 1,000 | 2,000 | 166M | 0.2 | 60,000 |
| 10,000 | 20,000 | 1.66B | 2.0 | 600,000 |
| 50,000 | 100,000 | 8.3B | 10.0 | 3,000,000 |

### Monthly LLM Cost (with ~70% cache hit rate)

| DAU | gpt-4o | gpt-4o-mini | o3-mini | claude-haiku-3.5 | Ollama |
|-----|--------|-------------|---------|-----------------|--------|
| **100** | $111 | $7 | $49 | $43 | $0 |
| **1,000** | $1,110 | $72 | $486 | $432 | $0 |
| **10,000** | $11,100 | $720 | $4,860 | $4,320 | $0 |
| **50,000** | $55,500 | $3,600 | $24,300 | $21,600 | $0 |

---

## 4. Infrastructure Cost (Monthly, AWS)

| Component | 100 DAU | 1K DAU | 10K DAU | 50K DAU |
|-----------|---------|--------|---------|---------|
| **Compute** (FastAPI workers) | 1× t3.medium ($30) | 2× c6i.large ($120) | 4× c6i.xlarge ($480) | 8× c6i.2xlarge ($1,920) |
| **PostgreSQL** (RDS) | db.t3.micro ($15) | db.t3.medium ($65) | db.r6g.large ($250) | db.r6g.xlarge ($500) |
| **Redis** (ElastiCache) | cache.t3.micro ($12) | cache.t3.small ($25) | cache.r6g.large ($180) | cache.r6g.xlarge ($360) |
| **ChromaDB** (embedded) | included | included | dedicated ($100) | dedicated ($300) |
| **Tavily** (web search) | Free tier | $50 | $200 | $500 |
| **Load balancer + misc** | $20 | $30 | $50 | $100 |
| **Infra subtotal** | **~$77** | **~$290** | **~$1,260** | **~$3,680** |

---

## 5. Total Monthly Cost (Infra + LLM)

| DAU | gpt-4o | gpt-4o-mini | o3-mini | Self-hosted (Ollama) |
|-----|--------|-------------|---------|---------------------|
| **100** | **$188** | **$84** | **$126** | **$77** + GPU* |
| **1,000** | **$1,400** | **$362** | **$776** | **$290** + GPU* |
| **10,000** | **$12,360** | **$1,980** | **$6,120** | **$1,260** + GPU* |
| **50,000** | **$59,180** | **$7,280** | **$27,980** | **$3,680** + GPU* |

*Self-hosted GPU: 1× A100 (~$2.5K/mo) handles ~2 RPS, 4× A100 (~$10K/mo) for 50K DAU*

---

## 6. LangGraph Platform vs Self-Hosted

### Current Setup: 100% Local (Self-Hosted)
- LangGraph used as **open-source Python library** (MIT license)
- `StateGraph` compiled and invoked locally via `builder.compile()` / `graph.ainvoke()`
- No checkpointer, no LangSmith, no langgraph-sdk, no cloud hooks
- SSE streaming via own Redis pub/sub
- HITL barriers via Redis BLPOP/RPUSH
- 4-layer audit system built in-house

### LangGraph Platform Pricing

Each analysis run = ~42 node executions (27 agents + 8 barriers + 4 audit + 2 start/end + 1 adversarial).

| | Developer (Free) | Plus | Enterprise |
|--|-----------------|------|-----------|
| Node executions | 100K/mo free | **$0.001/node** | Custom |
| Deployment (prod) | — | **$0.0036/min ($156/mo)** | Custom |
| LangSmith | — | **$39/seat/mo** | Custom |
| Traces | 5K free | 10K free, $2.50/1K after | Custom |

### Cost per run on LangGraph Platform
```
42 nodes × $0.001 = $0.042/run (node fees only, LLM billed separately)
```

### Monthly Comparison

| DAU | Self-Hosted (gpt-4o-mini) | LangGraph Platform (all-in) | Platform Overhead |
|-----|--------------------------|----------------------------|--------------------|
| **100** | **$84** | $547 | 6.5× more |
| **1,000** | **$362** | $3,015 | 8.3× more |
| **10,000** | **$1,980** | $27,693 | 14× more |
| **50,000** | **$7,280** | $137,373 | **18.9× more** |

### LangGraph Platform Monthly Breakdown

| DAU | Nodes/mo | Node Cost | Prod Uptime | LangSmith (3 seats) | Traces | Platform Total | + LLM | Grand Total |
|-----|----------|-----------|-------------|---------------------|--------|---------------|-------|-------------|
| 100 | 252K | $252 | $156 | $117 | $15 | $540 | $7 | **$547** |
| 1K | 2.52M | $2,520 | $156 | $117 | $150 | $2,943 | $72 | **$3,015** |
| 10K | 25.2M | $25,200 | $156 | $117 | $1,500 | $26,973 | $720 | **$27,693** |
| 50K | 126M | $126,000 | $156 | $117 | $7,500 | $133,773 | $3,600 | **$137,373** |

---

## 7. Recommendation

**Stay self-hosted.** Reasons:

1. **Node fees exceed LLM costs** — At $0.042/run in platform tax vs $0.04/run for gpt-4o-mini, you'd pay LangChain more than OpenAI.
2. **Linear scaling with no volume discount** — 10K DAU = $27K/mo platform vs $2K self-hosted.
3. **You already have the features** — SSE streaming, HITL, audit, cost monitoring are all built.
4. **Only missing: checkpointer** — Add `PostgresSaver` if you need persistent state replay.

### Optimal cost strategy:
- **Mixed-model**: gpt-4o-mini for 22 data/analysis agents + gpt-4o for 5 synthesis agents = ~$0.15/run
- **Aggressive caching**: Current 30min/1hr TTLs are good; consider 2hr for stable data agents
- **"Quick" mode default**: 21 agents instead of 27 covers 90% of use cases at 75% cost

---

## 8. Pipeline Architecture Reference

### Wave Structure (8 waves, 27 agents)
```
Wave 0 (Data):       A0 Profile, A1 Financials, A2 Market, A3 Industry, A4 News
Wave 1 (Analysis):   A5 Revenue, A6 Profitability, A7 Balance, A8 Cash Flow, A9 Growth
Wave 2 (Valuation):  A10 DCF, A11 Comps, A12 Precedent, A13 SOTP
Wave 3 (Risk):       A14 Risk, A15 Management, A16 ESG, A17 Moat
Wave 4 (Synthesis):  A18 Thesis, A19 Executive Summary
Wave 5 (Decision):   A20 IC Memo
Wave 6 (Specialized):A21 M&A, A22 LBO, A23 IPO, A24 Credit, A25 OpModel
Wave 7 (Sensitivity):A26 Sensitivity
```

### Cache TTLs
```
Pipeline cache:  1 hour
Agent cache:     30 minutes (per agent, overridable)
DB freshness:    profile=7d, market=15min, financials=event-driven, news=1hr
```

### Infrastructure Dependencies
```
PostgreSQL:  6 tables (profiles, market, financials, news, freshness, audit)
Redis:       Cache + event bus (pub/sub for SSE + BLPOP/RPUSH for HITL)
ChromaDB:    4 RAG collections (risk_factors, mda, proxy, industry_reports)
Ollama/API:  LLM gateway (OpenAI-compatible endpoint)
Tavily:      Web search (optional)
yfinance:    Market data (free)
edgartools:  SEC filings (free)
```

### Cost Monitor
Built-in safeguards at `app/persona_systems/audit/cost_monitor.py`:
```
max_pipeline_cost_usd:    $2.00
max_agent_calls:          3 per agent per run (loop detection)
max_agent_latency_ms:     60s
max_pipeline_duration_ms: 5 min
max_total_tokens:         500K
```

---

*Sources: LangGraph Platform Pricing (langchain.com), ZenML LangGraph Pricing Guide, LangSmith Plans (langchain.com)*
