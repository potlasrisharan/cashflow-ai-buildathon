"""
GET   /api/anomalies               → List anomalies with filters
GET   /api/anomalies/{id}          → Single anomaly + linked transaction
PATCH /api/anomalies/{id}/resolve  → Resolve an anomaly
PATCH /api/anomalies/{id}/dismiss  → Dismiss an anomaly
POST  /api/anomalies/scan          → Re-run anomaly detection on recent transactions
"""
from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime
from uuid import UUID

from db import supabase
from services.anomaly_service import recalculate_month_anomalies
from routes._validators import month_bounds

router = APIRouter()
PAGE_SIZE = 1000
ID_BATCH_SIZE = 200


class ResolveBody(BaseModel):
    resolved_by: Optional[str] = "Finance Team"
    note: Optional[str] = None


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[idx: idx + size] for idx in range(0, len(items), size)]


def _fetch_transaction_ids_for_month(month: str) -> list[str]:
    start, end = month_bounds(month)
    rows: list[str] = []
    offset = 0

    while True:
        resp = (
            supabase.table("transactions")
            .select("id")
            .gte("date", start)
            .lt("date", end)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        rows.extend(str(row["id"]) for row in chunk if row.get("id"))
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def _fetch_anomalies_for_transaction_ids(transaction_ids: list[str]) -> list[dict]:
    ids = [txn_id for txn_id in transaction_ids if txn_id]
    if not ids:
        return []

    rows: list[dict] = []
    for batch in _chunked(ids, ID_BATCH_SIZE):
        resp = (
            supabase.table("anomalies")
            .select("*, transactions(date,vendor,amount,department,category,payment_method,invoice_no)")
            .in_("transaction_id", batch)
            .execute()
        )
        rows.extend(resp.data or [])

    rows.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return rows


@router.get("")
def list_anomalies(
    status:   Optional[Literal["open", "reviewed", "resolved", "dismissed"]] = Query(None, description="open|reviewed|resolved|dismissed"),
    severity: Optional[Literal["critical", "warning", "info"]] = Query(None, description="critical|warning|info"),
    month:    Optional[str] = Query(None, description="YYYY-MM"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    if month:
        txn_ids = _fetch_transaction_ids_for_month(month)
        scoped_rows = _fetch_anomalies_for_transaction_ids(txn_ids)
        data_source = scoped_rows
        if status:
            data_source = [row for row in data_source if row.get("status") == status]
        if severity:
            data_source = [row for row in data_source if row.get("severity") == severity]

        offset = (page - 1) * per_page
        data = data_source[offset: offset + per_page]
        count_source = scoped_rows
    else:
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

        count_source = []
        count_offset = 0
        while True:
            all_resp = (
                supabase.table("anomalies")
                .select("severity,status")
                .range(count_offset, count_offset + PAGE_SIZE - 1)
                .execute()
            )
            chunk = all_resp.data or []
            count_source.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            count_offset += PAGE_SIZE

    counts = {
        "total":     len(count_source),
        "open":      sum(1 for a in count_source if a["status"] == "open"),
        "critical":  sum(1 for a in count_source if a["severity"] == "critical"),
        "warning":   sum(1 for a in count_source if a["severity"] == "warning"),
        "info":      sum(1 for a in count_source if a["severity"] == "info"),
        "resolved":  sum(1 for a in count_source if a["status"] == "resolved"),
    }

    # Estimated financial impact for the currently scoped result set
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
def get_anomaly(anomaly_id: UUID = Path(...)):
    resp = (
        supabase.table("anomalies")
        .select("*, transactions(*)")
        .eq("id", str(anomaly_id))
        .single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    return resp.data


@router.patch("/{anomaly_id}/resolve")
def resolve_anomaly(anomaly_id: UUID, body: ResolveBody):
    updates = {
        "status":      "resolved",
        "resolved_at": datetime.utcnow().isoformat(),
        "resolved_by": body.resolved_by or "Finance Team",
    }
    if body.note:
        updates["description"] = body.note

    resp = supabase.table("anomalies").update(updates).eq("id", str(anomaly_id)).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    # Mark linked transaction as reviewed
    anom = resp.data[0]
    if anom.get("transaction_id"):
        supabase.table("transactions").update({"status": "paid"}).eq("id", anom["transaction_id"]).execute()

    return {"status": "resolved", "anomaly": resp.data[0]}


@router.patch("/{anomaly_id}/dismiss")
def dismiss_anomaly(anomaly_id: UUID):
    resp = (
        supabase.table("anomalies")
        .update({"status": "dismissed", "resolved_at": datetime.utcnow().isoformat()})
        .eq("id", str(anomaly_id))
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
    result = await recalculate_month_anomalies(month)
    return {"message": "Scan complete", **result}
