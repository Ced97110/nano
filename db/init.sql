-- Nano Bana Pro — Financial data store
-- Stores only data that flows through agents. No overfetching.
--
-- Refresh strategy:
--   company_profiles:  re-fetch when stale > 7 days (rarely changes)
--   market_snapshots:  re-fetch when stale > 15 minutes (prices move)
--   financial_statements: re-fetch when next_earnings_date is passed (quarterly)
--   company_news:      re-fetch when stale > 1 hour (news cycle)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ────────────────────────────────────────────
-- 1. Company Profile (consumed by A0)
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS company_profiles (
    ticker          TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    sector          TEXT,
    industry        TEXT,
    description     TEXT,
    headquarters    TEXT,
    employees       INTEGER,
    exchange        TEXT,
    website         TEXT,
    founded         INTEGER,
    officers        JSONB DEFAULT '[]',       -- [{name, title, age, total_pay}]
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL DEFAULT 'yahoo_finance'
);

-- ────────────────────────────────────────────
-- 2. Market Snapshot (consumed by A2)
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_snapshots (
    ticker                      TEXT PRIMARY KEY,
    share_price                 DOUBLE PRECISION,
    previous_close              DOUBLE PRECISION,
    day_high                    DOUBLE PRECISION,
    day_low                     DOUBLE PRECISION,
    fifty_two_week_high         DOUBLE PRECISION,
    fifty_two_week_low          DOUBLE PRECISION,
    market_cap                  BIGINT,
    enterprise_value            BIGINT,
    volume                      BIGINT,
    avg_volume                  BIGINT,
    -- Valuation multiples
    pe_ratio                    DOUBLE PRECISION,
    forward_pe                  DOUBLE PRECISION,
    peg_ratio                   DOUBLE PRECISION,
    price_to_sales              DOUBLE PRECISION,
    price_to_book               DOUBLE PRECISION,
    ev_to_ebitda                DOUBLE PRECISION,
    ev_to_revenue               DOUBLE PRECISION,
    -- Per-share
    trailing_eps                DOUBLE PRECISION,
    forward_eps                 DOUBLE PRECISION,
    book_value                  DOUBLE PRECISION,
    -- Ownership & short interest
    beta                        DOUBLE PRECISION,
    shares_outstanding          BIGINT,
    float_shares                BIGINT,
    short_ratio                 DOUBLE PRECISION,
    short_percent_of_float      DOUBLE PRECISION,
    held_percent_insiders       DOUBLE PRECISION,
    held_percent_institutions   DOUBLE PRECISION,
    -- Dividend
    dividend_yield              DOUBLE PRECISION,
    dividend_rate               DOUBLE PRECISION,
    payout_ratio                DOUBLE PRECISION,
    -- Moving averages
    fifty_day_average           DOUBLE PRECISION,
    two_hundred_day_average     DOUBLE PRECISION,
    -- Analyst targets
    target_mean_price           DOUBLE PRECISION,
    target_high_price           DOUBLE PRECISION,
    target_low_price            DOUBLE PRECISION,
    recommendation_key          TEXT,
    number_of_analyst_opinions  INTEGER,
    -- Meta
    currency                    TEXT DEFAULT 'USD',
    fetched_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    source                      TEXT NOT NULL DEFAULT 'yahoo_finance'
);

-- ────────────────────────────────────────────
-- 3. Financial Statements (consumed by A1)
--    One row per ticker per period (FY/Q)
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS financial_statements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker              TEXT NOT NULL,
    period_end_date     DATE NOT NULL,           -- e.g. 2025-09-30
    period_type         TEXT NOT NULL,            -- 'annual' or 'quarterly'
    -- Income statement (stored in USD, raw values)
    total_revenue       BIGINT,
    cost_of_revenue     BIGINT,
    gross_profit        BIGINT,
    operating_income    BIGINT,
    net_income          BIGINT,
    ebitda              BIGINT,
    basic_eps           DOUBLE PRECISION,
    diluted_eps         DOUBLE PRECISION,
    research_and_development BIGINT,
    sga_expense         BIGINT,
    -- Balance sheet
    total_assets        BIGINT,
    total_liabilities   BIGINT,
    stockholders_equity BIGINT,
    cash_and_equivalents BIGINT,
    total_debt          BIGINT,
    net_debt            BIGINT,
    current_assets      BIGINT,
    current_liabilities BIGINT,
    -- Cash flow
    operating_cash_flow BIGINT,
    investing_cash_flow BIGINT,
    financing_cash_flow BIGINT,
    free_cash_flow      BIGINT,
    capital_expenditure BIGINT,
    -- Meta
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    source              TEXT NOT NULL DEFAULT 'yahoo_finance',
    UNIQUE(ticker, period_end_date, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fin_ticker_period ON financial_statements(ticker, period_type, period_end_date DESC);

-- ────────────────────────────────────────────
-- 4. Company News (consumed by A4)
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS company_news (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker          TEXT NOT NULL,
    title           TEXT NOT NULL,
    summary         TEXT,
    publisher       TEXT,
    link            TEXT,
    published_at    TIMESTAMPTZ,
    content_type    TEXT,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          TEXT NOT NULL DEFAULT 'yahoo_finance'
);

CREATE INDEX IF NOT EXISTS idx_news_ticker_date ON company_news(ticker, fetched_at DESC);

-- ────────────────────────────────────────────
-- 5. Refresh tracker — knows WHEN to re-fetch
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_freshness (
    ticker              TEXT NOT NULL,
    data_type           TEXT NOT NULL,          -- 'profile' | 'market' | 'financials' | 'news'
    last_fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_earnings_date  DATE,                  -- from yfinance, used to trigger financials refresh
    stale_after_seconds INTEGER NOT NULL,      -- TTL: profile=604800, market=900, financials=0 (event-driven), news=3600
    PRIMARY KEY (ticker, data_type)
);

-- ────────────────────────────────────────────
-- 6. Immutable Audit Trail (append-only, 7-year retention minimum)
--    Every agent action logged with timestamp, agent ID, action type,
--    input params, output summary, and data sources.
-- ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_trail (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     UUID NOT NULL,
    event_type      TEXT NOT NULL,
    agent_id        TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_workflow ON audit_trail(workflow_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_trail(created_at);

-- Prevent modifications: only INSERT allowed (append-only immutability)
REVOKE UPDATE, DELETE ON audit_trail FROM PUBLIC;

COMMENT ON TABLE audit_trail IS 'Immutable audit log. INSERT-only. Minimum 7-year retention per compliance policy. Archive to cold storage after 12 months.';
