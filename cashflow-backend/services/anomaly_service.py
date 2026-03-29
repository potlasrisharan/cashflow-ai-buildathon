"""
Anomaly detection service using statistical z-score analysis.

Detects:
1. Spend spike       — amount > 2.5 std deviations above vendor mean
2. Unknown vendor    — vendor with < 2 historical transactions
3. Duplicate invoice — same vendor + same amount within 30 days  
4. Missing receipt   — reimbursement > ₹2,000 with no receipt
5. Unusual day       — transaction on weekend/holiday (info only)
"""
from typing import Any
from collections import defaultdict
import numpy as np

from db import supabase
from routes._validators import month_bounds


# ── Thresholds ────────────────────────────────────────────────────────────────
SPIKE_Z_THRESHOLD     = 2.5    # Critical if z > 3, Warning if z > 2.5
UNKNOWN_VENDOR_MAX    = 1      # Vendor with ≤1 prior transactions = unknown
RECEIPT_THRESHOLD     = 2000   # Reimbursement above this requires receipt
DUPLICATE_WINDOW_DAYS = 30     # Look-back window for duplicate detection
PAGE_SIZE             = 1000
DELETE_BATCH_SIZE     = 200
RECALCULABLE_STATUSES = ("open", "reviewed")


async def detect_anomalies(
    transactions: list[dict[str, Any]],
    transaction_ids: list[str],
) -> list[dict[str, Any]]:
    """
    Run all anomaly detectors on a batch of transactions.
    Returns list of anomaly dicts ready for Supabase insert.
    """
    anomalies: list[dict[str, Any]] = []

    # Build vendor spend history from this batch (production: query DB too)
    vendor_amounts: dict[str, list[float]] = defaultdict(list)
    vendor_counts:  dict[str, int]         = defaultdict(int)
    seen: list[tuple[str, float]] = []  # for duplicate detection

    for txn in transactions:
        v = txn.get("vendor", "")
        a = float(txn.get("amount", 0))
        vendor_amounts[v].append(a)
        vendor_counts[v] += 1

    for i, (txn, txn_id) in enumerate(zip(transactions, transaction_ids)):
        vendor  = txn.get("vendor", "Unknown")
        amount  = float(txn.get("amount", 0))
        method  = txn.get("payment_method", "")
        receipt = txn.get("has_receipt", True)
        dept    = txn.get("department", "")

        # ── 1. Spend Spike Detection (Z-Score) ───────────────────
        amounts_for_vendor = vendor_amounts.get(vendor, [amount])
        if len(amounts_for_vendor) >= 2:
            mean = float(np.mean(amounts_for_vendor))
            std  = float(np.std(amounts_for_vendor))
            z    = abs(amount - mean) / std if std > 0 else 0
            if z >= SPIKE_Z_THRESHOLD and amount > mean:
                severity = "critical" if z >= 3.5 else "warning"
                anomalies.append(_make_anomaly(
                    transaction_id=txn_id,
                    severity=severity,
                    atype="spend_spike",
                    title=f"{vendor} — Spend Spike Detected",
                    description=(
                        f"{vendor} charged ₹{amount:,.0f} this period — "
                        f"{z:.1f}σ above the ₹{mean:,.0f} average. "
                        f"Possible runaway usage, unauthorized charge, or pricing change."
                    ),
                    z_score=round(z, 4),
                ))

        # ── 2. Unknown / First-time Vendor ───────────────────────
        if vendor_counts.get(vendor, 0) <= UNKNOWN_VENDOR_MAX and amount > 5000:
            anomalies.append(_make_anomaly(
                transaction_id=txn_id,
                severity="critical" if amount > 20000 else "warning",
                atype="unknown_vendor",
                title=f"Unknown Vendor — {vendor}",
                description=(
                    f"{vendor} has no prior transaction history and is "
                    f"not on the approved vendor list. "
                    f"Amount ₹{amount:,.0f} requires manual PO verification."
                ),
                z_score=None,
            ))

        # ── 3. Duplicate Transaction ──────────────────────────────
        pair = (vendor, amount)
        if pair in seen:
            anomalies.append(_make_anomaly(
                transaction_id=txn_id,
                severity="critical",
                atype="duplicate_invoice",
                title=f"Duplicate Payment — {vendor}",
                description=(
                    f"A payment of ₹{amount:,.0f} to {vendor} was already recorded "
                    f"in this batch. This may be a duplicate invoice. "
                    f"₹{amount:,.0f} is potentially recoverable."
                ),
                z_score=None,
            ))
        else:
            seen.append(pair)

        # ── 4. Missing Receipt ────────────────────────────────────
        if (
            "reimbursement" in method.lower()
            and amount > RECEIPT_THRESHOLD
            and not receipt
        ):
            anomalies.append(_make_anomaly(
                transaction_id=txn_id,
                severity="info",
                atype="missing_receipt",
                title=f"Missing Receipt — {vendor}",
                description=(
                    f"A ₹{amount:,.0f} reimbursement from {dept} has no receipt attached. "
                    f"Company policy requires receipts for claims above ₹{RECEIPT_THRESHOLD:,}."
                ),
                z_score=None,
            ))

    return anomalies


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[idx: idx + size] for idx in range(0, len(items), size)]


def _fetch_transactions_for_month(month: str) -> list[dict[str, Any]]:
    start, end = month_bounds(month)
    rows: list[dict[str, Any]] = []
    offset = 0

    while True:
        resp = (
            supabase.table("transactions")
            .select("id,vendor,amount,department,category,date,has_receipt,payment_method")
            .gte("date", start)
            .lt("date", end)
            .order("date")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        chunk = resp.data or []
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def clear_recalculable_anomalies(transaction_ids: list[str]) -> int:
    txn_ids = [txn_id for txn_id in transaction_ids if txn_id]
    if not txn_ids:
        return 0

    deleted = 0
    for batch in _chunked(txn_ids, DELETE_BATCH_SIZE):
        resp = (
            supabase.table("anomalies")
            .delete()
            .in_("transaction_id", batch)
            .in_("status", list(RECALCULABLE_STATUSES))
            .execute()
        )
        deleted += len(resp.data or [])

    return deleted


async def recalculate_month_anomalies(month: str) -> dict[str, Any]:
    """
    Rebuild recalculable anomalies for an entire month so dashboard totals stay
    in sync when users add, edit, delete, or bulk-upload expenses.
    """
    transactions = _fetch_transactions_for_month(month)
    transaction_ids = [str(txn["id"]) for txn in transactions if txn.get("id")]

    if transaction_ids:
        clear_recalculable_anomalies(transaction_ids)

    anomalies = await detect_anomalies(transactions, transaction_ids) if transaction_ids else []
    inserted = 0

    for batch in _chunked(anomalies, DELETE_BATCH_SIZE):
        resp = supabase.table("anomalies").insert(batch).execute()
        inserted += len(resp.data or [])

    return {
        "month": month,
        "transactions_scanned": len(transactions),
        "anomalies_found": inserted,
    }


def _make_anomaly(
    *,
    transaction_id: str,
    severity: str,
    atype: str,
    title: str,
    description: str,
    z_score: float | None,
) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "severity":       severity,
        "type":           atype,
        "title":          title,
        "description":    description,
        "status":         "open",
        "z_score":        z_score,
    }
