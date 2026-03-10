"""Domain service — Deterministic DCF (Discounted Cash Flow) computation.

Pure math, zero external dependencies. Used by the DCF valuation agent.
"""


def compute_dcf(
    free_cash_flows: list[float],
    wacc: float,
    terminal_growth_rate: float = 0.025,
    shares_outstanding: float | None = None,
) -> dict:
    if wacc <= terminal_growth_rate:
        return {"error": "WACC must exceed terminal growth rate"}

    pv_fcfs = []
    for i, fcf in enumerate(free_cash_flows, start=1):
        pv = fcf / (1 + wacc) ** i
        pv_fcfs.append(round(pv, 2))

    last_fcf = free_cash_flows[-1] if free_cash_flows else 0
    terminal_fcf = last_fcf * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (wacc - terminal_growth_rate)
    n = len(free_cash_flows)
    pv_terminal = terminal_value / (1 + wacc) ** n

    enterprise_value = sum(pv_fcfs) + pv_terminal

    result = {
        "pv_fcfs": pv_fcfs,
        "terminal_value": round(terminal_value, 2),
        "pv_terminal_value": round(pv_terminal, 2),
        "enterprise_value": round(enterprise_value, 2),
    }

    if shares_outstanding and shares_outstanding > 0:
        result["per_share_value"] = round(enterprise_value / shares_outstanding, 2)

    return result


def sensitivity_table(
    base_fcfs: list[float],
    wacc_range: list[float],
    growth_range: list[float],
    shares_outstanding: float | None = None,
) -> list[dict]:
    rows = []
    for wacc in wacc_range:
        for g in growth_range:
            dcf = compute_dcf(base_fcfs, wacc, g, shares_outstanding)
            rows.append({
                "wacc": wacc,
                "terminal_growth": g,
                "enterprise_value": dcf.get("enterprise_value"),
                "per_share_value": dcf.get("per_share_value"),
            })
    return rows
