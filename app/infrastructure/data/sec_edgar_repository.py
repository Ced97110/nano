"""Infrastructure adapter — SEC EDGAR financial data repository.

Implements FinancialDataRepository using the edgartools library for
SEC filings, XBRL financials, and structured company facts.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import structlog

from app.domain.interfaces.financial_data_repository import FinancialDataRepository

logger = structlog.get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=2)


def _safe(val) -> object:
    """Convert non-JSON-safe types."""
    if val is None:
        return None
    type_name = type(val).__name__
    if type_name in ("int64", "int32", "float64", "float32"):
        return float(val) if "float" in type_name else int(val)
    if type_name == "Timestamp":
        return str(val)
    return val


def _set_edgar_identity():
    """Set EDGAR identity (required by SEC for API access)."""
    try:
        from edgar import set_identity
        set_identity("NanoBana AI research@nanobana.com")
    except Exception:
        pass


class SECEdgarRepository(FinancialDataRepository):
    """Fetches financial data from SEC EDGAR via edgartools."""

    def __init__(self) -> None:
        _set_edgar_identity()

    async def get_company_filings(self, ticker: str, form_type: str = "10-K", count: int = 3) -> list[dict]:
        def _fetch():
            try:
                from edgar import Company
                company = Company(ticker)
                filings_obj = company.get_filings(form=form_type)
                result = []
                for f in filings_obj[:count]:
                    result.append({
                        "form": f.form,
                        "filing_date": str(f.filing_date),
                        "accession_number": str(getattr(f, "accession_no", "")),
                        "company": getattr(f, "company", ticker),
                    })
                return result
            except Exception as exc:
                logger.warning("sec_edgar.filings.error", ticker=ticker, error=str(exc))
                return []

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_financial_statements(self, ticker: str) -> dict:
        def _fetch():
            try:
                from edgar import Company
                company = Company(ticker)
                # Get latest 10-K filing
                filings_obj = company.get_filings(form="10-K")
                filing = filings_obj[0]  # latest filing
                if not filing:
                    return {"error": "No 10-K filings found", "data_source": "sec_edgar"}

                result = {
                    "form": filing.form,
                    "filing_date": str(filing.filing_date),
                    "accession_number": str(getattr(filing, "accession_no", "")),
                    "company": getattr(filing, "company", ticker),
                    "data_source": "sec_edgar",
                    "fetched_at": datetime.utcnow().isoformat(),
                }

                # Try XBRL extraction
                try:
                    xbrl = filing.xbrl()
                    if xbrl is not None:
                        # Try to get financials via the financials property
                        if hasattr(xbrl, "facts"):
                            facts_df = xbrl.facts
                            if facts_df is not None and hasattr(facts_df, "to_dict"):
                                result["xbrl_facts"] = facts_df.to_dict()
                except Exception:
                    pass

                return result
            except Exception as exc:
                logger.warning("sec_edgar.financials.error", ticker=ticker, error=str(exc))
                return {"error": str(exc), "data_source": "sec_edgar"}

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_company_facts(self, ticker: str) -> dict:
        def _fetch():
            try:
                from edgar import Company
                company = Company(ticker)
                facts = company.get_facts()
                if facts is None:
                    return {"error": "No company facts found", "data_source": "sec_edgar"}

                # Extract key facts as flat dict
                result = {
                    "company_name": str(getattr(company, "name", ticker)),
                    "cik": str(getattr(company, "cik", "")),
                }

                # Get most recent values for important metrics
                key_concepts = [
                    "us-gaap:Revenues",
                    "us-gaap:NetIncomeLoss",
                    "us-gaap:Assets",
                    "us-gaap:StockholdersEquity",
                    "us-gaap:EarningsPerShareBasic",
                    "us-gaap:OperatingIncomeLoss",
                ]
                for concept in key_concepts:
                    try:
                        fact_data = facts[concept]
                        if fact_data is not None:
                            # Get the most recent annual value
                            df = fact_data.to_dataframe() if hasattr(fact_data, "to_dataframe") else None
                            if df is not None and not df.empty:
                                recent = df.iloc[-1]
                                result[concept.split(":")[-1]] = {
                                    "value": _safe(recent.get("val")),
                                    "period": str(recent.get("end", "")),
                                    "form": str(recent.get("form", "")),
                                }
                    except Exception:
                        continue

                result["data_source"] = "sec_edgar"
                result["fetched_at"] = datetime.utcnow().isoformat()
                return result
            except Exception as exc:
                logger.warning("sec_edgar.facts.error", ticker=ticker, error=str(exc))
                return {"error": str(exc), "data_source": "sec_edgar"}

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)
