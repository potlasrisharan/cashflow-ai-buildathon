"""
GET  /api/budgets                   → All budgets for a month
GET  /api/budgets/utilization       → Budget vs actual spend per dept
POST /api/budgets                   → Set/upsert budget for a dept
DELETE /api/budgets/{dept}/{month}  → Remove a budget entry
"""
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field

from db import supabase
from routes._validators import month_bounds

router = APIRouter()


class BudgetSet(BaseModel):
    department: str = Field(..., min_length=1, max_length=80)
    month: str
    budget_amount: float = Field(..., gt=0)


@router.get("")
def get_budgets(month: str = Query("2025-01")):
    month_bounds(month)
    resp = (
        supabase.table("budgets")
        .select("*")
        .eq("month", month)
        .order("department")
        .execute()
    )
    return {"month": month, "data": resp.data or []}


@router.get("/utilization")
def budget_utilization(month: str = Query("2025-01")):
    """Returns budget vs actual spend with utilization % per department."""
    start, end = month_bounds(month)

    budget_resp = (
        supabase.table("budgets")
        .select("department,budget_amount")
        .eq("month", month)
        .execute()
    )
    txn_resp = (
        supabase.table("transactions")
        .select("department,amount")
        .gte("date", start)
        .lt("date", end)
        .execute()
    )

    budgets: dict[str, float] = {
        b["department"]: b["budget_amount"] for b in (budget_resp.data or [])
    }
    spend: dict[str, float] = {}
    for t in (txn_resp.data or []):
        spend[t["department"]] = spend.get(t["department"], 0) + t["amount"]

    depts = sorted(set(list(budgets.keys()) + list(spend.keys())))
    rows = []
    for dept in depts:
        budget_amt = budgets.get(dept, 0)
        spent_amt  = spend.get(dept, 0)
        remaining  = budget_amt - spent_amt
        pct        = round(spent_amt / budget_amt * 100, 1) if budget_amt else 0
        status     = (
            "over"    if pct > 100  else
            "at_risk" if pct >= 85  else
            "on_track"
        )
        rows.append({
            "department":    dept,
            "budget":        round(budget_amt, 2),
            "spent":         round(spent_amt, 2),
            "remaining":     round(remaining, 2),
            "utilization_pct": pct,
            "status":        status,
        })

    total_budget = sum(r["budget"] for r in rows)
    total_spent  = sum(r["spent"]  for r in rows)
    over_budget  = [r["department"] for r in rows if r["status"] == "over"]

    return {
        "month": month,
        "summary": {
            "total_budget":    round(total_budget, 2),
            "total_spent":     round(total_spent, 2),
            "total_remaining": round(total_budget - total_spent, 2),
            "overall_pct":     round(total_spent / total_budget * 100, 1) if total_budget else 0,
            "depts_over":      over_budget,
        },
        "departments": rows,
    }


@router.post("", status_code=201)
def set_budget(body: BudgetSet):
    """Upsert a department budget — updates if exists, inserts if new."""
    month_bounds(body.month)
    resp = (
        supabase.table("budgets")
        .upsert({
            "department":    body.department,
            "month":         body.month,
            "budget_amount": body.budget_amount,
        }, on_conflict="department,month")
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to save budget")
    return resp.data[0]


@router.delete("/{department}/{month}", status_code=204)
def delete_budget(department: str, month: str):
    month_bounds(month)
    supabase.table("budgets").delete().eq("department", department).eq("month", month).execute()
