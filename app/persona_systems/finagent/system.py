"""
FinAgent Pro — 27-agent financial analysis pipeline powered by LangGraph.

DAG topology (8 execution waves):
    Wave 0 (Data Gathering):    A0 Profile, A1 Financials, A2 Market, A3 Industry, A4 News
    Wave 1 (Analysis):          A5 Revenue, A6 Profitability, A7 Balance Sheet, A8 Cash Flow, A9 Growth
    Wave 2 (Valuation):         A10 DCF, A11 Comps, A12 Precedent Txns, A13 SOTP
    Wave 3 (Risk & Quality):    A14 Risk, A15 Management, A16 ESG, A17 Moat
    Wave 4 (Synthesis):         A18 Investment Thesis, A19 Executive Summary
    Wave 5 (IC Decision):       A20 Investment Committee Memo
    Wave 6 (Specialized):       A21 M&A, A22 LBO, A23 IPO, A24 Credit, A25 Operating Model
    Wave 7 (Sensitivity):       A26 Sensitivity Analysis

Dependencies flow inward only:
    system.py → domain interfaces (via base_system)
    system.py → agent classes (domain logic)
    system.py does NOT import infrastructure directly
"""

import structlog

from app.domain.interfaces.audit_store import AuditEvent
from app.persona_systems.audit.cost_monitor import BudgetExceededError, CostMonitor
from app.persona_systems.audit.llm_audit import adversarial_review
from app.persona_systems.base_system import BasePersonaSystem

from app.persona_systems.finagent.agents.a0_company_profile import CompanyProfileAgent
from app.persona_systems.finagent.agents.a1_financial_statements import FinancialStatementsAgent
from app.persona_systems.finagent.agents.a2_market_data import MarketDataAgent
from app.persona_systems.finagent.agents.a3_industry_context import IndustryContextAgent
from app.persona_systems.finagent.agents.a4_news_sentiment import NewsSentimentAgent
from app.persona_systems.finagent.agents.a5_revenue_model import RevenueModelAgent
from app.persona_systems.finagent.agents.a6_profitability import ProfitabilityAgent
from app.persona_systems.finagent.agents.a7_balance_sheet import BalanceSheetAgent
from app.persona_systems.finagent.agents.a8_cash_flow import CashFlowAgent
from app.persona_systems.finagent.agents.a9_growth_trajectory import GrowthTrajectoryAgent
from app.persona_systems.finagent.agents.a10_dcf import DCFAgent
from app.persona_systems.finagent.agents.a11_comps import CompsAgent
from app.persona_systems.finagent.agents.a12_precedent_transactions import PrecedentTransactionsAgent
from app.persona_systems.finagent.agents.a13_sum_of_parts import SumOfPartsAgent
from app.persona_systems.finagent.agents.a14_risk_assessment import RiskAssessmentAgent
from app.persona_systems.finagent.agents.a15_management_quality import ManagementQualityAgent
from app.persona_systems.finagent.agents.a16_esg_governance import ESGGovernanceAgent
from app.persona_systems.finagent.agents.a17_competitive_moat import CompetitiveMoatAgent
from app.persona_systems.finagent.agents.a18_investment_thesis import InvestmentThesisAgent
from app.persona_systems.finagent.agents.a19_executive_summary import ExecutiveSummaryAgent
from app.persona_systems.finagent.agents.a20_ic_memo import ICMemoAgent
from app.persona_systems.finagent.agents.a21_ma_analysis import MAAnalysisAgent
from app.persona_systems.finagent.agents.a22_lbo_model import LBOModelAgent
from app.persona_systems.finagent.agents.a23_ipo_readiness import IPOReadinessAgent
from app.persona_systems.finagent.agents.a24_credit_analysis import CreditAnalysisAgent
from app.persona_systems.finagent.agents.a25_operating_model import OperatingModelAgent
from app.persona_systems.finagent.agents.a26_sensitivity import SensitivityAnalysisAgent

logger = structlog.get_logger(__name__)

# Maps analysis_type → set of agent IDs to include.
# "full" runs everything; others filter to specific subsets.
ANALYSIS_TYPE_AGENTS: dict[str, set[str] | None] = {
    "full": None,  # None means run all agents
    "quick": {
        "finagent.A0_company_profile", "finagent.A1_financial_statements",
        "finagent.A2_market_data", "finagent.A3_industry_context",
        "finagent.A4_news_sentiment", "finagent.A5_revenue_model",
        "finagent.A6_profitability", "finagent.A7_balance_sheet",
        "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
        "finagent.A10_dcf", "finagent.A11_comps",
        "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
        "finagent.A14_risk_assessment", "finagent.A15_management_quality",
        "finagent.A16_esg_governance", "finagent.A17_competitive_moat",
        "finagent.A18_investment_thesis", "finagent.A19_executive_summary",
        "finagent.A20_ic_memo",
    },
    "ma_focused": {
        "finagent.A0_company_profile", "finagent.A1_financial_statements",
        "finagent.A2_market_data", "finagent.A3_industry_context",
        "finagent.A4_news_sentiment", "finagent.A5_revenue_model",
        "finagent.A6_profitability", "finagent.A7_balance_sheet",
        "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
        "finagent.A10_dcf", "finagent.A11_comps",
        "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
        "finagent.A14_risk_assessment", "finagent.A15_management_quality",
        "finagent.A16_esg_governance", "finagent.A17_competitive_moat",
        "finagent.A18_investment_thesis", "finagent.A19_executive_summary",
        "finagent.A20_ic_memo", "finagent.A21_ma_analysis",
    },
    "credit_focused": {
        "finagent.A0_company_profile", "finagent.A1_financial_statements",
        "finagent.A2_market_data", "finagent.A3_industry_context",
        "finagent.A4_news_sentiment", "finagent.A5_revenue_model",
        "finagent.A6_profitability", "finagent.A7_balance_sheet",
        "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
        "finagent.A10_dcf", "finagent.A11_comps",
        "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
        "finagent.A14_risk_assessment", "finagent.A15_management_quality",
        "finagent.A16_esg_governance", "finagent.A17_competitive_moat",
        "finagent.A18_investment_thesis", "finagent.A19_executive_summary",
        "finagent.A20_ic_memo", "finagent.A22_lbo_model",
        "finagent.A24_credit_analysis",
    },
    "valuation_deep": {
        "finagent.A0_company_profile", "finagent.A1_financial_statements",
        "finagent.A2_market_data", "finagent.A3_industry_context",
        "finagent.A4_news_sentiment", "finagent.A5_revenue_model",
        "finagent.A6_profitability", "finagent.A7_balance_sheet",
        "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
        "finagent.A10_dcf", "finagent.A11_comps",
        "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
        "finagent.A14_risk_assessment", "finagent.A15_management_quality",
        "finagent.A16_esg_governance", "finagent.A17_competitive_moat",
        "finagent.A18_investment_thesis", "finagent.A19_executive_summary",
        "finagent.A20_ic_memo", "finagent.A22_lbo_model",
        "finagent.A25_operating_model", "finagent.A26_sensitivity",
    },
}


class FinAgentPro(BasePersonaSystem):
    """FinAgent Pro — 27-agent financial analysis pipeline.

    Supports dynamic orchestration via ``analysis_type`` which filters
    the DAG to run only the relevant subset of agents.

    All infrastructure access goes through the injected ports
    (self._llm, self._cache, self._events) inherited from BasePersonaSystem.
    """

    system_id = "finagent"
    PIPELINE_CACHE_TTL = 3600

    def __init__(self, **kwargs) -> None:
        self._active_agent_filter: set[str] | None = None
        super().__init__(**kwargs)

    def _get_active_agents(self) -> dict:
        """Return the agents dict filtered by the current analysis_type."""
        if self._active_agent_filter is None:
            return self.agents
        return {
            aid: agent for aid, agent in self.agents.items()
            if aid in self._active_agent_filter
        }

    def _get_filtered_dependency_graph(self) -> dict[str, list[str]]:
        """Return the dependency graph filtered to only include active agents."""
        full_graph = self.get_agent_dependency_graph()
        if self._active_agent_filter is None:
            return full_graph
        return {
            aid: [dep for dep in deps if dep in self._active_agent_filter]
            for aid, deps in full_graph.items()
            if aid in self._active_agent_filter
        }

    def _compile_graph(self):
        """Override base to support dynamic agent filtering."""
        active_agents = self._get_active_agents()
        if not active_agents:
            return super()._compile_graph()

        from langgraph.graph import END, START, StateGraph
        from app.persona_systems.base_system import PipelineState

        builder = StateGraph(PipelineState)

        for agent_id, agent in active_agents.items():
            builder.add_node(agent_id, agent)

        waves = self._compute_waves()

        for wave_idx in range(len(waves)):
            if wave_idx < len(waves) - 1:
                validator = self._make_validator(wave_idx, waves[wave_idx])
                builder.add_node(f"_barrier_{wave_idx}", validator)

        for wave_idx, wave_agents in enumerate(waves):
            if wave_idx == 0:
                for aid in wave_agents:
                    builder.add_edge(START, aid)
            else:
                prev_barrier = f"_barrier_{wave_idx - 1}"
                for aid in wave_agents:
                    builder.add_edge(prev_barrier, aid)

            if wave_idx < len(waves) - 1:
                barrier_name = f"_barrier_{wave_idx}"
                for aid in wave_agents:
                    builder.add_edge(aid, barrier_name)
            else:
                for aid in wave_agents:
                    builder.add_edge(aid, END)

        return builder.compile()

    def _compute_waves(self) -> list[list[str]]:
        """Override base to use the filtered dependency graph."""
        dag = self._get_filtered_dependency_graph()
        completed: set[str] = set()
        remaining = set(dag.keys())
        waves: list[list[str]] = []
        while remaining:
            ready = {
                a for a in remaining
                if all(d in completed for d in dag.get(a, []))
            }
            if not ready:
                raise RuntimeError(
                    f"DAG deadlock in {self.system_id}: "
                    f"remaining={remaining}, completed={completed}"
                )
            waves.append(sorted(ready))
            completed |= ready
            remaining -= ready
        return waves

    def _build_agents(self) -> dict:
        # Inject the same ports into every agent (Dependency Inversion)
        deps = (self._llm, self._cache, self._events, self._data)
        audit = self._audit_store
        ws = self._web_search
        agents = [
            CompanyProfileAgent(*deps, audit_store=audit, web_search=ws),
            FinancialStatementsAgent(*deps, audit_store=audit, web_search=ws),
            MarketDataAgent(*deps, audit_store=audit, web_search=ws),
            IndustryContextAgent(*deps, audit_store=audit, web_search=ws),
            NewsSentimentAgent(*deps, audit_store=audit, web_search=ws),
            RevenueModelAgent(*deps, audit_store=audit, web_search=ws),
            ProfitabilityAgent(*deps, audit_store=audit, web_search=ws),
            BalanceSheetAgent(*deps, audit_store=audit, web_search=ws),
            CashFlowAgent(*deps, audit_store=audit, web_search=ws),
            GrowthTrajectoryAgent(*deps, audit_store=audit, web_search=ws),
            DCFAgent(*deps, audit_store=audit, web_search=ws),
            CompsAgent(*deps, audit_store=audit, web_search=ws),
            PrecedentTransactionsAgent(*deps, audit_store=audit, web_search=ws),
            SumOfPartsAgent(*deps, audit_store=audit, web_search=ws),
            RiskAssessmentAgent(*deps, audit_store=audit, web_search=ws),
            ManagementQualityAgent(*deps, audit_store=audit, web_search=ws),
            ESGGovernanceAgent(*deps, audit_store=audit, web_search=ws),
            CompetitiveMoatAgent(*deps, audit_store=audit, web_search=ws),
            InvestmentThesisAgent(*deps, audit_store=audit, web_search=ws),
            ExecutiveSummaryAgent(*deps, audit_store=audit, web_search=ws),
            ICMemoAgent(*deps, audit_store=audit, web_search=ws),
            MAAnalysisAgent(*deps, audit_store=audit, web_search=ws),
            LBOModelAgent(*deps, audit_store=audit, web_search=ws),
            IPOReadinessAgent(*deps, audit_store=audit, web_search=ws),
            CreditAnalysisAgent(*deps, audit_store=audit, web_search=ws),
            OperatingModelAgent(*deps, audit_store=audit, web_search=ws),
            SensitivityAnalysisAgent(*deps, audit_store=audit, web_search=ws),
        ]
        return {a.agent_id: a for a in agents}

    def get_agent_dependency_graph(self) -> dict[str, list[str]]:
        W0 = [
            "finagent.A0_company_profile",
            "finagent.A1_financial_statements",
            "finagent.A2_market_data",
            "finagent.A3_industry_context",
            "finagent.A4_news_sentiment",
        ]
        return {
            "finagent.A0_company_profile": [],
            "finagent.A1_financial_statements": [],
            "finagent.A2_market_data": [],
            "finagent.A3_industry_context": [],
            "finagent.A4_news_sentiment": [],
            "finagent.A5_revenue_model": W0,
            "finagent.A6_profitability": W0,
            "finagent.A7_balance_sheet": W0,
            "finagent.A8_cash_flow": W0,
            "finagent.A9_growth_trajectory": W0,
            "finagent.A10_dcf": W0 + [
                "finagent.A5_revenue_model", "finagent.A6_profitability",
                "finagent.A7_balance_sheet", "finagent.A8_cash_flow",
                "finagent.A9_growth_trajectory",
            ],
            "finagent.A11_comps": W0 + [
                "finagent.A5_revenue_model", "finagent.A6_profitability",
            ],
            "finagent.A12_precedent_transactions": W0 + [
                "finagent.A5_revenue_model",
            ],
            "finagent.A13_sum_of_parts": W0 + [
                "finagent.A5_revenue_model", "finagent.A6_profitability",
            ],
            "finagent.A14_risk_assessment": W0 + [
                "finagent.A7_balance_sheet", "finagent.A9_growth_trajectory",
                "finagent.A10_dcf",
            ],
            "finagent.A15_management_quality": ["finagent.A0_company_profile"],
            "finagent.A16_esg_governance": [
                "finagent.A0_company_profile", "finagent.A4_news_sentiment",
            ],
            "finagent.A17_competitive_moat": W0 + [
                "finagent.A5_revenue_model", "finagent.A6_profitability",
            ],
            "finagent.A18_investment_thesis": [
                "finagent.A0_company_profile", "finagent.A2_market_data",
                "finagent.A5_revenue_model", "finagent.A6_profitability",
                "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
                "finagent.A10_dcf", "finagent.A11_comps",
                "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
                "finagent.A14_risk_assessment", "finagent.A17_competitive_moat",
            ],
            "finagent.A19_executive_summary": [
                "finagent.A0_company_profile", "finagent.A2_market_data",
                "finagent.A14_risk_assessment", "finagent.A15_management_quality",
                "finagent.A16_esg_governance", "finagent.A17_competitive_moat",
                "finagent.A18_investment_thesis",
            ],
            # Wave 5 — IC Memo (depends on all synthesis agents)
            "finagent.A20_ic_memo": [
                "finagent.A19_executive_summary",
                "finagent.A18_investment_thesis",
            ],
            # Wave 6 — Specialized agents (parallel)
            "finagent.A21_ma_analysis": [
                "finagent.A0_company_profile", "finagent.A3_industry_context",
                "finagent.A11_comps", "finagent.A12_precedent_transactions",
            ],
            "finagent.A22_lbo_model": [
                "finagent.A1_financial_statements", "finagent.A2_market_data",
                "finagent.A7_balance_sheet", "finagent.A8_cash_flow",
                "finagent.A10_dcf", "finagent.A11_comps",
            ],
            "finagent.A23_ipo_readiness": [
                "finagent.A0_company_profile", "finagent.A1_financial_statements",
                "finagent.A2_market_data", "finagent.A5_revenue_model",
                "finagent.A11_comps", "finagent.A15_management_quality",
                "finagent.A16_esg_governance",
            ],
            "finagent.A24_credit_analysis": [
                "finagent.A1_financial_statements", "finagent.A2_market_data",
                "finagent.A6_profitability", "finagent.A7_balance_sheet",
                "finagent.A8_cash_flow", "finagent.A10_dcf",
            ],
            "finagent.A25_operating_model": [
                "finagent.A0_company_profile", "finagent.A1_financial_statements",
                "finagent.A3_industry_context", "finagent.A5_revenue_model",
                "finagent.A6_profitability", "finagent.A8_cash_flow",
                "finagent.A9_growth_trajectory",
            ],
            # Wave 7 — Sensitivity (depends on DCF + LBO + Operating Model)
            "finagent.A26_sensitivity": [
                "finagent.A1_financial_statements", "finagent.A2_market_data",
                "finagent.A10_dcf", "finagent.A11_comps",
                "finagent.A22_lbo_model", "finagent.A25_operating_model",
            ],
        }

    async def run_pipeline(
        self,
        request: dict,
        intent: dict,
        cross_system_context: dict | None = None,
    ) -> dict:
        entities = intent.get("entities_detected", {})
        companies = entities.get("companies", [])
        countries = entities.get("countries", [])
        entity = (
            companies[0] if companies
            else countries[0] if countries
            else intent.get("ticker", "UNKNOWN")
        ).upper()
        request_id = str(request.get("id") or "")

        # ── Dynamic orchestration: filter DAG by analysis_type ──
        analysis_type = request.get("analysis_type", "full")
        allowed_agents = ANALYSIS_TYPE_AGENTS.get(analysis_type)
        if allowed_agents is not None:
            self._active_agent_filter = allowed_agents
        else:
            self._active_agent_filter = None  # Run all agents

        # Use cached graph if available; compile and cache otherwise
        if analysis_type not in self._graph_cache:
            self._graph_cache[analysis_type] = self._compile_graph()
        self._compiled_graph = self._graph_cache[analysis_type]

        # ── AG-UI: RUN_STARTED (via injected publisher) ──
        # Published BEFORE cache check so the frontend always receives it,
        # regardless of whether the pipeline runs fully or returns cached.
        active_agents = self._get_active_agents()
        waves = self._compute_waves()
        if request_id:
            await self._events.publish(request_id, {
                "type": "RUN_STARTED",
                "runId": request_id,
                "threadId": self.system_id,
                "total_agents": len(active_agents),
                "waves": len(waves),
                "analysis_type": analysis_type,
            })

        # ── Pipeline cache (via injected repository) ──
        cache_key_suffix = f":{analysis_type}" if analysis_type != "full" else ""
        try:
            cached = await self._cache.get_pipeline(self.system_id, entity + cache_key_suffix)
            if cached:
                logger.info("finagent.pipeline_cache.hit", entity=entity, analysis_type=analysis_type)
                cached["_cache"] = {"hit": True, "level": "pipeline"}
                if request_id:
                    await self._events.publish(request_id, {
                        "type": "RUN_FINISHED", "runId": request_id, "cached": True,
                    })
                return cached
        except Exception:
            pass

        # ── Trigger background ingestion for unknown tickers ──
        # Data should already be in DB from pre-warming. If not, kick off
        # background ingestion so it's ready for the next run. The pipeline
        # starts immediately with whatever data is available.
        ingestion_svc = self._data.get("ingestion") if self._data else None
        if ingestion_svc:
            import asyncio
            asyncio.create_task(ingestion_svc.ingest_ticker_background(entity))

        # ── Audit: run_started ──
        if self._audit_store and request_id:
            try:
                await self._audit_store.log_event(AuditEvent(
                    workflow_id=request_id,
                    event_type="run_started",
                    payload={
                        "system_id": self.system_id,
                        "entity": entity,
                        "total_agents": len(active_agents),
                        "waves": len(waves),
                        "hitl_mode": request.get("mode", "express"),
                        "analysis_type": analysis_type,
                    },
                ))
            except Exception:
                pass

        # ── Execute LangGraph DAG with budget enforcement ──
        monitor = CostMonitor(
            pipeline_id=request_id,
            ticker=entity,
            analysis_type=analysis_type,
        )

        hitl_mode = request.get("mode", "express")
        initial_state = {
            "intent": intent,
            "request": request,
            "cross_system_context": cross_system_context or {},
            "agent_outputs": {},
            "request_id": request_id,
            "entity": entity,
            "hitl_mode": hitl_mode,
            "cost_monitor": monitor,
        }

        try:
            outputs, audit_log, cost_log = await self.execute_dag_with_audit(initial_state)
        except BudgetExceededError as exc:
            logger.error("finagent.budget_exceeded", entity=entity, error=str(exc))
            if request_id:
                await self._events.publish(request_id, {
                    "type": "RUN_ERROR",
                    "runId": request_id,
                    "error": str(exc),
                })
            report = monitor.generate_report()
            return {
                "type": "investment_dossier",
                "title": f"FinAgent Pro Analysis: {entity} (ABORTED — budget exceeded)",
                "entity": entity,
                "error": str(exc),
                "cost": report.to_dict(),
            }

        # ── Layer 4: Adversarial review of final output ──
        all_warnings = []
        for wave_key, wave_data in audit_log.items():
            if isinstance(wave_data, dict):
                all_warnings.extend(wave_data.get("schema_violations", []))

        adversarial = {}
        try:
            adversarial = await adversarial_review(
                self._llm, entity, outputs, all_warnings,
            )
        except Exception as exc:
            logger.warning("finagent.adversarial_review.failed", error=str(exc))

        # Track adversarial review cost
        adv_cost = adversarial.get("_cost_usd", 0.0)
        adv_tokens = adversarial.get("_tokens_used", 0)
        if adv_cost or adv_tokens:
            cost_log["adversarial_review"] = {
                "tokens_used": adv_tokens,
                "cost_usd": round(adv_cost, 6),
                "type": "adversarial_review",
            }

        # ── Cost summary ──
        total_tokens = sum(c.get("tokens_used", 0) for c in cost_log.values())
        total_cost = sum(c.get("cost_usd", 0.0) for c in cost_log.values())
        agent_costs = {
            k: v for k, v in cost_log.items()
            if not k.startswith("audit_") and k != "adversarial_review"
        }
        audit_costs = {
            k: v for k, v in cost_log.items()
            if k.startswith("audit_") or k == "adversarial_review"
        }

        logger.info(
            "finagent.pipeline.cost_summary",
            entity=entity,
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 4),
            agent_cost_usd=round(sum(c.get("cost_usd", 0) for c in agent_costs.values()), 4),
            audit_cost_usd=round(sum(c.get("cost_usd", 0) for c in audit_costs.values()), 4),
        )

        # ── Assemble result ──
        thesis = outputs.get("finagent.A18_investment_thesis", {})
        summary = outputs.get("finagent.A19_executive_summary", {})

        non_error_outputs = {
            k: v for k, v in outputs.items()
            if isinstance(v, dict) and "error" not in v
        }
        base_confidence = len(non_error_outputs) / max(len(outputs), 1)
        adversarial_confidence = adversarial.get("final_confidence_score")
        if isinstance(adversarial_confidence, (int, float)) and 0 <= adversarial_confidence <= 1:
            confidence = round((base_confidence * 0.6) + (adversarial_confidence * 0.4), 2)
        else:
            confidence = round(base_confidence, 2)

        # ── IC Memo (only present if A20 ran) ──
        ic_memo = outputs.get("finagent.A20_ic_memo", {})

        # ── Specialized agent outputs (only present if those agents ran) ──
        specialized = {}
        if "finagent.A21_ma_analysis" in outputs:
            specialized["ma_analysis"] = outputs["finagent.A21_ma_analysis"]
        if "finagent.A22_lbo_model" in outputs:
            specialized["lbo_model"] = outputs["finagent.A22_lbo_model"]
        if "finagent.A23_ipo_readiness" in outputs:
            specialized["ipo_readiness"] = outputs["finagent.A23_ipo_readiness"]
        if "finagent.A24_credit_analysis" in outputs:
            specialized["credit_analysis"] = outputs["finagent.A24_credit_analysis"]
        if "finagent.A25_operating_model" in outputs:
            specialized["operating_model"] = outputs["finagent.A25_operating_model"]
        if "finagent.A26_sensitivity" in outputs:
            specialized["sensitivity_analysis"] = outputs["finagent.A26_sensitivity"]

        result = {
            "type": "investment_dossier",
            "title": f"FinAgent Pro Analysis: {entity}",
            "entity": entity,
            "analysis_type": analysis_type,
            "content": {
                "executive_summary": summary,
                "investment_thesis": thesis,
                "ic_memo": ic_memo,
                "valuation": {
                    "dcf": outputs.get("finagent.A10_dcf", {}),
                    "comps": outputs.get("finagent.A11_comps", {}),
                    "precedent_transactions": outputs.get("finagent.A12_precedent_transactions", {}),
                    "sum_of_parts": outputs.get("finagent.A13_sum_of_parts", {}),
                },
                "fundamentals": {
                    "profile": outputs.get("finagent.A0_company_profile", {}),
                    "financials": outputs.get("finagent.A1_financial_statements", {}),
                    "market_data": outputs.get("finagent.A2_market_data", {}),
                    "revenue_model": outputs.get("finagent.A5_revenue_model", {}),
                    "profitability": outputs.get("finagent.A6_profitability", {}),
                    "balance_sheet": outputs.get("finagent.A7_balance_sheet", {}),
                    "cash_flow": outputs.get("finagent.A8_cash_flow", {}),
                    "growth": outputs.get("finagent.A9_growth_trajectory", {}),
                },
                "risk_and_quality": {
                    "risk_assessment": outputs.get("finagent.A14_risk_assessment", {}),
                    "management": outputs.get("finagent.A15_management_quality", {}),
                    "esg": outputs.get("finagent.A16_esg_governance", {}),
                    "competitive_moat": outputs.get("finagent.A17_competitive_moat", {}),
                },
                "specialized": specialized,
                "industry_context": outputs.get("finagent.A3_industry_context", {}),
                "news_sentiment": outputs.get("finagent.A4_news_sentiment", {}),
            },
            "confidence_score": round(confidence, 2),
            "agents_completed": len(non_error_outputs),
            "agents_total": len(outputs),
            "has_external_recipient": False,
            "_cache": {"hit": False, "level": "none"},
            "audit": {
                "wave_audits": audit_log,
                "adversarial_review": adversarial,
                "overall_quality": adversarial.get("overall_quality", "unknown"),
                "approved": adversarial.get("approved", True),
                "caveats": adversarial.get("suggested_caveats", []),
            },
            "cost": {
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
                "agent_costs": agent_costs,
                "audit_costs": audit_costs,
            },
        }

        # ── Cache result (via injected repository) ──
        try:
            await self._cache.set_pipeline(self.system_id, entity + cache_key_suffix, result, self.PIPELINE_CACHE_TTL)
        except Exception:
            pass

        # ── AG-UI: RUN_FINISHED (via injected publisher) ──
        if request_id:
            await self._events.publish(request_id, {
                "type": "RUN_FINISHED",
                "runId": request_id,
                "cached": False,
                "confidence": confidence,
                "total_agents": len(outputs),
                "recommendation": thesis.get("recommendation", "N/A"),
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
            })

        # ── Audit: run_finished ──
        if self._audit_store and request_id:
            try:
                await self._audit_store.log_event(AuditEvent(
                    workflow_id=request_id,
                    event_type="run_finished",
                    payload={
                        "system_id": self.system_id,
                        "entity": entity,
                        "confidence_score": confidence,
                        "agents_completed": len(non_error_outputs),
                        "agents_total": len(outputs),
                        "total_tokens": total_tokens,
                        "total_cost_usd": round(total_cost, 6),
                        "recommendation": thesis.get("recommendation", "N/A"),
                        "adversarial_approved": adversarial.get("approved", True),
                    },
                ))
            except Exception:
                pass

        return result
