"""
GET    /api/transactions                  → Paginated list with filters
POST   /api/transactions                  → Create transaction
GET    /api/transactions/{id}             → Single transaction
PATCH  /api/transactions/{id}             → Update status/notes
DELETE /api/transactions/{id}             → Delete transaction
GET    /api/transactions/stats/by-category → Aggregated spend by category
GET    /api/transactions/stats/by-dept     → Aggregated spend by dept
"""
from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel
from typing import Optional
from db import supabase
import uuid

router = APIRouter()

# ── Schemas ───────────────────────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    date: str                           # "YYYY-MM-DD"
    vendor: str
    category: str
    department: str
    amount: float
    payment_method: str = "Bank Transfer"
    invoice_no: Optional[str] = None
    status: str = "pending"
    has_receipt: bool = False
    notes: Optional[str] = None


class TransactionUpdate(BaseModel):
    status: Optional[str] = None
    category: Optional[str] = None
    department: Optional[str] = None
    notes: Optional[str] = None
    has_receipt: Optional[bool] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_transactions(
    month:      Optional[str] = Query(None, description="YYYY-MM"),
    department: Optional[str] = Query(None),
    category:   Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    vendor:     Optional[str] = Query(None),
    page:       int           = Query(1, ge=1),
    per_page:   int           = Query(50, ge=1, le=200),
):
    q = supabase.table("transactions").select("*").order("date", desc=True)

    if month:
        y, m = int(month[:4]), int(month[5:])
        next_m = f"{y}-{m+1:02d}" if m < 12 else f"{y+1}-01"
        q = q.gte("date", f"{month}-01").lt("date", f"{next_m}-01")
    if department:
        q = q.eq("department", department)
    if category:
        q = q.eq("category", category)
    if status:
        q = q.eq("status", status)
    if vendor:
        q = q.ilike("vendor", f"%{vendor}%")

    offset = (page - 1) * per_page
    q = q.range(offset, offset + per_page - 1)

    resp = q.execute()
    return {
        "data": resp.data or [],
        "page": page,
        "per_page": per_page,
        "count": len(resp.data or []),
    }


@router.post("", status_code=201)
def create_transaction(body: TransactionCreate):
    payload = body.model_dump()
    resp = supabase.table("transactions").insert(payload).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="Failed to create transaction")
    return resp.data[0]


@router.get("/stats/by-category")
def stats_by_category(month: str = Query("2025-01")):
    y, m = int(month[:4]), int(month[5:])
    next_m = f"{y}-{m+1:02d}" if m < 12 else f"{y+1}-01"

    resp = (
        supabase.table("transactions")
        .select("category,amount")
        .gte("date", f"{month}-01")
        .lt("date", f"{next_m}-01")
        .execute()
    )
    agg: dict[str, float] = {}
    for t in (resp.data or []):
        agg[t["category"]] = agg.get(t["category"], 0) + t["amount"]
    total = sum(agg.values())
    return [
        {"category": k, "amount": round(v, 2), "pct": round(v/total*100, 1) if total else 0}
        for k, v in sorted(agg.items(), key=lambda x: -x[1])
    ]


@router.get("/stats/by-dept")
def stats_by_dept(month: str = Query("2025-01")):
    y, m = int(month[:4]), int(month[5:])
    next_m = f"{y}-{m+1:02d}" if m < 12 else f"{y+1}-01"

    resp = (
        supabase.table("transactions")
        .select("department,amount")
        .gte("date", f"{month}-01")
        .lt("date", f"{next_m}-01")
        .execute()
    )
    agg: dict[str, float] = {}
    for t in (resp.data or []):
        agg[t["department"]] = agg.get(t["department"], 0) + t["amount"]
    total = sum(agg.values())
    return [
        {"department": k, "amount": round(v, 2), "pct": round(v/total*100, 1) if total else 0}
        for k, v in sorted(agg.items(), key=lambda x: -x[1])
    ]


@router.get("/{txn_id}")
def get_transaction(txn_id: str = Path(...)):
    resp = supabase.table("transactions").select("*").eq("id", txn_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return resp.data


@router.patch("/{txn_id}")
def update_transaction(txn_id: str, body: TransactionUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    resp = supabase.table("transactions").update(updates).eq("id", txn_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return resp.data[0]


@router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: str):
    supabase.table("transactions").delete().eq("id", txn_id).execute()
