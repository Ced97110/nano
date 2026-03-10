"""Cross-system pipeline registry.

Defines which agent outputs are exported and how systems feed each other.
"""

EXPORT_SCHEMAS: dict[str, dict[str, str]] = {
    "finagent": {
        "finagent.A14_risk_assessment": "risk_flags",
        "finagent.A4_news_sentiment": "sentiment",
        "finagent.A19_executive_summary": "executive_summary",
    },
}

CROSS_SYSTEM_PIPELINES: list[dict] = [
    {
        "source": "crip",
        "target": "finagent",
        "export_keys": ["risk_score", "anomalies", "early_warning"],
    },
    {
        "source": "strategist",
        "target": "finagent",
        "export_keys": ["competitive_landscape", "swot"],
    },
    {
        "source": "finagent",
        "target": "pr_specialist",
        "export_keys": ["risk_flags", "sentiment"],
    },
]
