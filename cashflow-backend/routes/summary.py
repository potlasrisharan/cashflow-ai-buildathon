"""
GET /api/summary                    → Dashboard KPI cards
GET /api/summary/spend-by-category  → Donut chart data
GET /api/summary/spend-by-dept      → Department bar chart
GET /api/summary/trend              → Daily spend trend line
"""
from fastapi import APIRouter, Query
from db import supabase
from routes._validators import month_bounds

router = APIRouter()


@router.get("")
def get_dashboard_summary(month: str = Query("2025-01", description="Month in YYYY-MM format")):
    """Returns all KPI metrics for the dashboard header cards."""

    # ── All transactions for the month ────────────────────────
    start, end = month_bounds(month)

    txn_resp = (
        supabase.table("transactions")
        .select("*")
        .gte("date", start)
        .lt("date", end)
        .execute()
    )
    txns = txn_resp.data or []

    total_spend = sum(t["amount"] for t in txns)
    txn_count   = len(txns)

    # ── Budget total for the month ─────────────────────────────
    budget_resp = (
        supabase.table("budgets")
        .select("budget_amount")
        .eq("month", month)
        .execute()
    )
    total_budget = sum(b["budget_amount"] for b in (budget_resp.data or []))
    budget_remaining = total_budget - total_spend

    # ── Open anomalies ─────────────────────────────────────────
    anom_resp = (
        supabase.table("anomalies")
        .select("*")
        .eq("status", "open")
        .execute()
    )
    anomalies = anom_resp.data or []
    critical_count = sum(1 for a in anomalies if a["severity"] == "critical")

    # ── Vendor with highest spend ──────────────────────────────
    vendor_spend: dict[str, float] = {}
    for t in txns:
        vendor_spend[t["vendor"]] = vendor_spend.get(t["vendor"], 0) + t["amount"]
    top_vendor = max(vendor_spend, key=lambda k: vendor_spend[k]) if vendor_spend else "N/A"
    top_vendor_amount = max(vendor_spend.values()) if vendor_spend else 0

    # ── Depts over budget ──────────────────────────────────────
    dept_spend: dict[str, float] = {}
    for t in txns:
        dept_spend[t["department"]] = dept_spend.get(t["department"], 0) + t["amount"]

    budget_by_dept: dict[str, float] = {}
    budget_dept_resp = (
        supabase.table("budgets")
        .select("department,budget_amount")
        .eq("month", month)
        .execute()
    )
    for b in (budget_dept_resp.data or []):
        budget_by_dept[b["department"]] = b["budget_amount"]

    depts_over = [
        d for d, s in dept_spend.items()
        if budget_by_dept.get(d, 0) > 0 and s > budget_by_dept[d]
    ]

    # ── Subscription cost proxy ────────────────────────────────
    subscription_cats = {"Software"}
    sub_spend = sum(t["amount"] for t in txns if t["category"] in subscription_cats)

    return {
        "month": month,
        "total_spend": round(total_spend, 2),
        "total_budget": round(total_budget, 2),
        "budget_remaining": round(budget_remaining, 2),
        "budget_utilized_pct": round((total_spend / total_budget * 100) if total_budget else 0, 1),
        "transaction_count": txn_count,
        "anomaly_count": len(anomalies),
        "critical_anomaly_count": critical_count,
        "top_vendor": top_vendor,
        "top_vendor_amount": round(top_vendor_amount, 2),
        "top_vendor_pct": round((top_vendor_amount / total_spend * 100) if total_spend else 0, 1),
        "depts_over_budget": depts_over,
        "depts_over_budget_count": len(depts_over),
        "subscription_cost": round(sub_spend, 2),
        "forecast_next_month": round(total_spend * 1.081, 2),  # +8.1% trend
    }


@router.get("/spend-by-category")
def spend_by_category(month: str = Query("2025-01")):
    """Returns spend aggregated by category — used for donut/bar charts."""
    start, end = month_bounds(month)

    resp = (
        supabase.table("transactions")
        .select("category,amount")
        .gte("date", start)
        .lt("date", end)
        .execute()
    )
    agg: dict[str, float] = {}
    for t in (resp.data or []):
        agg[t["category"]] = agg.get(t["category"], 0) + t["amount"]

    total = sum(agg.values())
    return {
        "labels": list(agg.keys()),
        "values": [round(v, 2) for v in agg.values()],
        "percentages": [round(v / total * 100, 1) if total else 0 for v in agg.values()],
        "total": round(total, 2),
    }


@router.get("/spend-by-dept")
def spend_by_dept(month: str = Query("2025-01")):
    """Returns spend + budget per department — used for grouped bar chart."""
    start, end = month_bounds(month)

    txn_resp = (
        supabase.table("transactions")
        .select("department,amount")
        .gte("date", start)
        .lt("date", end)
        .execute()
    )
    budget_resp = (
        supabase.table("budgets")
        .select("department,budget_amount")
        .eq("month", month)
        .execute()
    )

    spend: dict[str, float] = {}
    for t in (txn_resp.data or []):
        spend[t["department"]] = spend.get(t["department"], 0) + t["amount"]

    budget: dict[str, float] = {b["department"]: b["budget_amount"] for b in (budget_resp.data or [])}
    depts = sorted(set(list(spend.keys()) + list(budget.keys())))

    return {
        "labels":  depts,
        "spend":   [round(spend.get(d, 0), 2) for d in depts],
        "budget":  [round(budget.get(d, 0), 2) for d in depts],
        "utilization": [
            round(spend.get(d, 0) / budget[d] * 100, 1) if budget.get(d) else 0
            for d in depts
        ],
    }


@router.get("/trend")
def spend_trend(month: str = Query("2025-01")):
    """Returns daily cumulative and daily spend — used for trend line chart."""
    start, end = month_bounds(month)

    resp = (
        supabase.table("transactions")
        .select("date,amount,category")
        .gte("date", start)
        .lt("date", end)
        .order("date")
        .execute()
    )

    daily: dict[str, float] = {}
    by_cat: dict[str, dict[str, float]] = {}  # cat → {date → amount}

    for t in (resp.data or []):
        d = t["date"][:10]
        daily[d] = daily.get(d, 0) + t["amount"]
        cat = t["category"]
        if cat not in by_cat:
            by_cat[cat] = {}
        by_cat[cat][d] = by_cat[cat].get(d, 0) + t["amount"]

    dates = sorted(daily.keys())
    return {
        "labels": dates,
        "daily_total": [round(daily[d], 2) for d in dates],
        "by_category": {
            cat: [round(vals.get(d, 0), 2) for d in dates]
            for cat, vals in by_cat.items()
        },
    }
