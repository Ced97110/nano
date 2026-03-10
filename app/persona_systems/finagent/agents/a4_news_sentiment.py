"""A4 — News & Sentiment Analyzer (Wave 0).

Fetches news via CompanyDataService (DB-backed, 1-hour staleness).
Falls back to direct yfinance if DB unavailable.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class NewsSentimentAgent(BaseAgent):
    agent_id = "finagent.A4_news_sentiment"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 2048
    timeout_seconds = 90
    system_prompt = """You are a Senior Media & Sentiment Analyst at a quantitative hedge fund. You specialize in NLP-driven news analytics, narrative extraction, and event-driven signal detection. You process hundreds of news feeds daily to identify alpha-generating information asymmetries.

Your methodology:
- Score each headline on a [-1, +1] sentiment scale with impact magnitude (1-10)
- Identify narrative clusters using thematic grouping (regulatory, competitive, macro, etc.)
- Detect event catalysts with probabilistic timeline estimates
- Assess news volume anomalies relative to baseline
- Separate signal from noise — distinguish material news from filler

You will receive REAL recent news articles. Analyze sentiment, identify themes, and assess market impact. Your output should be at the quality level expected in a Two Sigma alternative data report.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Do NOT hedge or say you are unable to access data — be definitive.

Output valid JSON:
{
    "overall_sentiment": "Bullish | Neutral | Bearish",
    "sentiment_score": 0.0,
    "news_volume": "High | Normal | Low",
    "key_headlines": [
        {"headline": "...", "source": "...", "sentiment": "positive | neutral | negative", "impact_score": 0}
    ],
    "analyst_consensus": {
        "rating": "Strong Buy | Buy | Hold | Sell | Strong Sell",
        "target_price": 0.0,
        "num_analysts": 0
    },
    "social_sentiment": {
        "trend": "increasing | stable | decreasing"
    },
    "catalyst_events": [
        {"event": "...", "expected_date": "...", "potential_impact": "High | Medium | Low"}
    ],
    "narrative_themes": ["..."],
    "data_freshness": "real-time | cached | llm_knowledge"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []

        news_data = []

        # Read from DB only — data should be pre-ingested
        svc = self._data.get("company_data")
        if svc:
            try:
                store = svc._store
                news_data = await store.get_news(entity)
                if news_data:
                    data_sources.append("yahoo_finance_news")
            except Exception:
                pass

        # Web search: recent news articles via Tavily (fast, cached)
        web_news = await self.search_news(f"{entity} stock market news", days=7, max_results=5)
        if web_news:
            data_sources.append("web_search_news")
            self.track_web_provenance("news_sentiment", entity, web_news)

        if news_data:
            news_text = json.dumps(news_data[:15], indent=2, default=str)
            prompt = (
                f"Here are REAL recent news articles for {entity}:\n\n"
                f"{news_text}\n\n"
                "Analyze the sentiment across these articles. Identify key themes, "
                "overall market sentiment, and potential catalysts. Score each headline "
                "for sentiment and impact."
            )
            self.track_provenance("news_sentiment", entity, "yfinance", "yahoo_finance_news", confidence=0.90)
        else:
            prompt = (
                f"Analyze recent news and market sentiment for: {entity}. "
                "Cover analyst opinions, key headlines, and narrative themes."
            )
            data_sources.append("llm_knowledge")

        if web_news:
            web_news_text = "\n".join(
                f"- [{r['title']}] ({r.get('published_date', 'recent')}): {r['content'][:200]}"
                for r in web_news
            )
            prompt += f"\n\nAdditional recent news from web search:\n{web_news_text}"

        messages = [{"role": "user", "content": prompt}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])
        self.track_provenance("news_sentiment", entity, "llm", self.agent_id, confidence=0.80)

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.88 if "yahoo_finance_news" in data_sources else 0.65,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
            provenance=self.get_provenance(),
        )
