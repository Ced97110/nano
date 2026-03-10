"""Port — financial data repository interface (SEC filings / regulatory data).

Provides access to SEC EDGAR filings, XBRL financial statements, and
structured regulatory data. Domain never knows the data source.
"""

from abc import ABC, abstractmethod


class FinancialDataRepository(ABC):
    @abstractmethod
    async def get_company_filings(self, ticker: str, form_type: str = "10-K", count: int = 3) -> list[dict]:
        """Return recent filings metadata: [{form, filing_date, accession_number, period}]."""
        ...

    @abstractmethod
    async def get_financial_statements(self, ticker: str) -> dict:
        """Return structured financials from latest filing: income_statement, balance_sheet, cash_flow."""
        ...

    @abstractmethod
    async def get_company_facts(self, ticker: str) -> dict:
        """Return XBRL company facts: revenue, net_income, assets, etc. across periods."""
        ...
