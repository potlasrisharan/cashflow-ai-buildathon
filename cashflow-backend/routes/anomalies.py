"""
GET   /api/anomalies               → List anomalies with filters
GET   /api/anomalies/{id}          → Single anomaly + linked transaction
PATCH /api/anomalies/{id}/resolve  → Resolve an anomaly
PATCH /api/anomalies/{id}/dismiss  → Dismiss an anomaly
POST  /api/anomalies/scan          → Re-run anomaly detection on recent transactions
"""
from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from db import supabase
from services.anomaly_service import detect_anomalies

router = APIRouter()


class ResolveBody(BaseModel):
    resolved_by: Optional[str] = "Finance Team"
    note: Optional[str] = None


@router.get("")
def list_anomalies(
    status:   Optional[str] = Query(None, description="open|reviewed|resolved|dismissed"),
    severity: Optional[str] = Query(None, description="critical|warning|info"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    q = (
        supabase.table("anomalies")
        .select("*, transactions(date,vendor,amount,department,category,payment_method,invoice_no)")
        .order("created_at", desc=True)
    )
    if status:
        q = q.eq("status", status)
    if severity:
        q = q.eq("severity", severity)

    offset = (page - 1) * per_page
    q = q.range(offset, offset + per_page - 1)

    resp = q.execute()
    data = resp.data or []

    # Summarize counts
    all_resp = supabase.table("anomalies").select("severity,status").execute()
    all_anom = all_resp.data or []

    counts = {
        "total":     len(all_anom),
        "open":      sum(1 for a in all_anom if a["status"] == "open"),
        "critical":  sum(1 for a in all_anom if a["severity"] == "critical"),
        "warning":   sum(1 for a in all_anom if a["severity"] == "warning"),
        "info":      sum(1 for a in all_anom if a["severity"] == "info"),
        "resolved":  sum(1 for a in all_anom if a["status"] == "resolved"),
    }

    # Estimated financial impact
    financial_impact = 0.0
    for a in data:
        txn = a.get("transactions") or {}
        if isinstance(txn, dict) and a["status"] == "open":
            financial_impact += float(txn.get("amount", 0))

    return {
        "data": data,
        "counts": counts,
        "financial_impact": round(financial_impact, 2),
        "page": page,
        "per_page": per_page,
    }


@router.get("/{anomaly_id}")
def get_anomaly(anomaly_id: str = Path(...)):
    resp = (
        supabase.table("anomalies")
        .select("*, transactions(*)")
        .eq("id", anomaly_id)
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return resp.data


@router.patch("/{anomaly_id}/resolve")
def resolve_anomaly(anomaly_id: str, body: ResolveBody):
    updates = {
        "status":      "resolved",
        "resolved_at": datetime.utcnow().isoformat(),
        "resolved_by": body.resolved_by or "Finance Team",
    }
    if body.note:
        updates["description"] = body.note

    resp = supabase.table("anomalies").update(updates).eq("id", anomaly_id).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    # Mark linked transaction as reviewed
    anom = resp.data[0]
    if anom.get("transaction_id"):
        supabase.table("transactions").update({"status": "paid"}).eq("id", anom["transaction_id"]).execute()

    return {"status": "resolved", "anomaly": resp.data[0]}


@router.patch("/{anomaly_id}/dismiss")
def dismiss_anomaly(anomaly_id: str):
    resp = (
        supabase.table("anomalies")
        .update({"status": "dismissed", "resolved_at": datetime.utcnow().isoformat()})
        .eq("id", anomaly_id)
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return {"status": "dismissed", "anomaly": resp.data[0]}


@router.post("/scan")
async def run_anomaly_scan(month: str = Query("2025-01")):
    """
    Re-scan all transactions for a month and insert newly detected anomalies.
    Safe to run multiple times — checks for duplicates via transaction_id.
    """
    y, m = int(month[:4]), int(month[5:])
    next_m = f"{y}-{m+1:02d}" if m < 12 else f"{y+1}-01"

    txn_resp = (
        supabase.table("transactions")
        .select("id,vendor,amount,department,category,date,has_receipt,payment_method")
        .gte("date", f"{month}-01")
        .lt("date", f"{next_m}-01")
        .execute()
    )
    txns = txn_resp.data or []
    if not txns:
        return {"message": "No transactions found for this month", "anomalies_found": 0}

    ids = [t["id"] for t in txns]
    records = [
        {
            "vendor":   t["vendor"],
            "amount":   t["amount"],
            "department": t["department"],
            "category": t["category"],
            "has_receipt": t.get("has_receipt", False),
            "payment_method": t.get("payment_method", ""),
        }
        for t in txns
    ]

    new_anomalies = await detect_anomalies(records, ids)

    # Filter out any already-existing anomaly for a transaction_id
    if new_anomalies:
        existing_resp = (
            supabase.table("anomalies")
            .select("transaction_id")
            .in_("transaction_id", ids)
            .execute()
        )
        existing_txn_ids = {a["transaction_id"] for a in (existing_resp.data or [])}
        new_anomalies = [a for a in new_anomalies if a["transaction_id"] not in existing_txn_ids]

    if new_anomalies:
        supabase.table("anomalies").insert(new_anomalies).execute()

    return {
        "message": f"Scan complete",
        "transactions_scanned": len(txns),
        "anomalies_found": len(new_anomalies),
    }
