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

PAGE_SIZE = 1000
ID_BATCH_SIZE = 200


def _fetch_all_transactions_for_month(month: str, columns: str = "*") -> list[dict]:
    """
    Supabase REST responses are commonly capped per request (often 1000 rows).
    Fetch in pages so dashboard metrics/charts use full-month data.
    """
    start, end = month_bounds(month)
    rows: list[dict] = []
    offset = 0

    while True:
        resp = (
            supabase.table("transactions")
            .select(columns)
            .gte("date", start)
            .lt("date", end)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def _fetch_all_open_anomalies(columns: str = "*") -> list[dict]:
    rows: list[dict] = []
    offset = 0

    while True:
        resp = (
            supabase.table("anomalies")
            .select(columns)
            .eq("status", "open")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[idx: idx + size] for idx in range(0, len(items), size)]


def _fetch_open_anomalies_for_transaction_ids(
    transaction_ids: list[str],
    columns: str = "*",
) -> list[dict]:
    ids = [txn_id for txn_id in transaction_ids if txn_id]
    if not ids:
        return []

    rows: list[dict] = []
    for batch in _chunked(ids, ID_BATCH_SIZE):
        resp = (
            supabase.table("anomalies")
            .select(columns)
            .eq("status", "open")
            .in_("transaction_id", batch)
            .execute()
        )
        rows.extend(resp.data or [])

    return rows


@router.get("/months")
def available_months():
    months: set[str] = set()

    txn_offset = 0
    while True:
        resp = (
            supabase.table("transactions")
            .select("date")
            .order("date", desc=True)
            .range(txn_offset, txn_offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        for row in chunk:
            date_value = str(row.get("date", ""))
            if len(date_value) >= 7:
                months.add(date_value[:7])
        if len(chunk) < PAGE_SIZE:
            break
        txn_offset += PAGE_SIZE

    budget_offset = 0
    while True:
        resp = (
            supabase.table("budgets")
            .select("month")
            .order("month", desc=True)
            .range(budget_offset, budget_offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        for row in chunk:
            month_value = str(row.get("month", ""))
            if month_value:
                months.add(month_value)
        if len(chunk) < PAGE_SIZE:
            break
        budget_offset += PAGE_SIZE

    return {"months": sorted(months, reverse=True)}


@router.get("")
def get_dashboard_summary(month: str = Query("2025-01", description="Month in YYYY-MM format")):
    """Returns all KPI metrics for the dashboard header cards."""

    # ── All transactions for the month ────────────────────────
    txns = _fetch_all_transactions_for_month(month, "*")

    total_spend = sum(t["amount"] for t in txns)
    txn_count   = len(txns)
    txn_ids = [str(t["id"]) for t in txns if t.get("id")]

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
    anomalies = _fetch_open_anomalies_for_transaction_ids(txn_ids, "*")
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
    txns = _fetch_all_transactions_for_month(month, "category,amount")
    agg: dict[str, float] = {}
    for t in txns:
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
    txns = _fetch_all_transactions_for_month(month, "department,amount")
    budget_resp = (
        supabase.table("budgets")
        .select("department,budget_amount")
        .eq("month", month)
        .execute()
    )

    spend: dict[str, float] = {}
    for t in txns:
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
    txns = _fetch_all_transactions_for_month(month, "date,amount,category")

    daily: dict[str, float] = {}
    by_cat: dict[str, dict[str, float]] = {}  # cat → {date → amount}

    for t in txns:
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
