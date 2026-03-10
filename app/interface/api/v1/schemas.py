"""API-layer Pydantic schemas — request/response shapes for HTTP boundary."""

from pydantic import BaseModel, Field


VALID_ANALYSIS_TYPES = {"full", "quick", "ma_focused", "credit_focused", "valuation_deep"}


class AnalysisCreateSchema(BaseModel):
    persona_system: str = Field(..., description="System ID e.g. 'finagent'")
    ticker: str = Field("", description="Company ticker symbol")
    query: str = Field("", description="Free-text query")
    country: str = Field("", description="Country name for geo-risk systems")
    mode: str = Field("express", description="HITL mode: 'express' (auto), 'analyst' (pause at data+valuation), 'review' (pause every wave)")
    analysis_type: str = Field("full", description="Analysis scope: 'full' (all agents), 'quick' (core only), 'ma_focused', 'credit_focused', 'valuation_deep'")


class AnalysisOutputSchema(BaseModel):
    request_id: str
    system_id: str
    result: dict
    cached: bool = False


class HITLFeedbackSchema(BaseModel):
    wave: int = Field(..., description="Wave index to provide feedback for (0-3)")
    action: str = Field("approve", description="'approve' | 'override' | 'reject' (re-run wave) | 'cancel' (abort workflow)")
    overrides: dict = Field(default_factory=dict, description="Agent output overrides: {agent_id: {key: value}}")
    notes: str = Field("", description="Optional analyst notes")


class SharingApprovalSchema(BaseModel):
    approved_by: str = Field("analyst", description="Identity of the approving user")


class SharingStatusSchema(BaseModel):
    approved: bool
    approved_at: str | None = None
    approved_by: str | None = None
