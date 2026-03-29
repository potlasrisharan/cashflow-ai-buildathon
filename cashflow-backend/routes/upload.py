"""
POST /api/upload/csv       → Upload CSV of expenses → AI categorization + anomaly detection
POST /api/upload/receipt   → Upload receipt image → OCR → extract amount/vendor/date
GET  /api/upload/history   → List all uploads
"""
from fastapi import APIRouter, File, UploadFile, HTTPException
from typing import Optional
import io
import pandas as pd

from db import supabase
from services.ai_service import categorize_transactions
from services.ocr_service import extract_receipt_data
from services.anomaly_service import detect_anomalies

router = APIRouter()

# ── Security limits ───────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_CSV_COLUMNS = {
    "date", "vendor", "amount", "department",
    "category", "payment_method", "invoice_no", "notes"
}

REQUIRED_CSV_COLUMNS = {"date", "vendor", "amount"}

ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/jpg", "application/pdf"}


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    Accepts a CSV file with at minimum: date, vendor, amount.
    - AI categorizes any row missing a category
    - Runs anomaly detection on all rows
    - Saves everything to Supabase
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted")

    content = await file.read()

    # ── Guard: file size ─────────────────────────────────────────────────────
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum allowed size is 10 MB.",
        )

    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse CSV: {e}")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Alias mapping for easier processing
    aliases = {
        "description": "vendor",
        "merchant": "vendor",
        "payee": "vendor",
        "total": "amount"
    }
    for alias, target in aliases.items():
        if alias in df.columns and target not in df.columns:
            df.rename(columns={alias: target}, inplace=True)

    missing = REQUIRED_CSV_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV is missing required columns: {missing}. "
                   f"Required: date, vendor, amount (Got: {list(df.columns)})"
        )

    df = df.where(pd.notnull(df), None)
    row_count = len(df)

    # ── AI Categorization ─────────────────────────────────────
    needs_cat = df[df.get("category", pd.Series(dtype=str)).isna()] if "category" in df.columns else df
    categorized_count = 0

    if len(needs_cat) > 0:
        rows_for_ai = needs_cat[["vendor", "amount"]].to_dict("records")
        ai_results = await categorize_transactions(rows_for_ai)
        for idx, result in zip(needs_cat.index, ai_results):
            df.at[idx, "category"]      = result.get("category", "Other")
            df.at[idx, "department"]     = result.get("department", "Operations")
            df.at[idx, "ai_confidence"]  = result.get("confidence", 0.75)
            categorized_count += 1
    else:
        categorized_count = row_count

    # ── Insert transactions ───────────────────────────────────
    records = []
    for _, row in df.iterrows():
        records.append({
            "date":           str(row.get("date", ""))[:10],
            "vendor":         str(row.get("vendor", "Unknown")),
            "category":       str(row.get("category", "Other")),
            "department":     str(row.get("department", "Operations")),
            "amount":         float(row.get("amount", 0)),
            "payment_method": str(row.get("payment_method", "Bank Transfer")),
            "invoice_no":     str(row.get("invoice_no", "")) if row.get("invoice_no") else None,
            "notes":          str(row.get("notes", "")) if row.get("notes") else None,
            "status":         "pending",
            "has_receipt":    False,
            "ai_confidence":  float(row.get("ai_confidence", 0.85)),
        })

    insert_resp = supabase.table("transactions").insert(records).execute()
    inserted_ids = [r["id"] for r in (insert_resp.data or [])]

    # ── Anomaly Detection ─────────────────────────────────────
    flagged_count = 0
    if inserted_ids:
        anomalies = await detect_anomalies(records, inserted_ids)
        flagged_count = len(anomalies)
        if anomalies:
            supabase.table("anomalies").insert(anomalies).execute()

    # ── Log the upload ────────────────────────────────────────
    supabase.table("uploads").insert({
        "filename":    file.filename,
        "row_count":   row_count,
        "categorized": categorized_count,
        "flagged":     flagged_count,
        "status":      "done",
    }).execute()

    return {
        "status":      "done",
        "filename":    file.filename,
        "rows":        row_count,
        "categorized": categorized_count,
        "flagged":     flagged_count,
        "inserted_ids": inserted_ids,
    }


@router.post("/receipt")
async def upload_receipt(file: UploadFile = File(...)):
    """
    Accepts JPEG/PNG receipt image.
    Sends to OCR.space → extracts vendor, amount, date.
    Returns extracted data for user to confirm before saving.
    """
    if file.content_type not in ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG/PNG/PDF files are supported")

    content = await file.read()

    # ── Guard: file size ─────────────────────────────────────────────────────
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File too large. Maximum allowed size is 10 MB.",
        )

    try:
        extracted = await extract_receipt_data(content, file.filename, file.content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR failed: {e}")

    return {
        "status":    "extracted",
        "filename":  file.filename,
        "extracted": extracted,
        "preview":   "Receipt parsed successfully. Review and confirm below.",
    }


@router.get("/history")
def upload_history(page: int = 1, per_page: int = 20):
    """Lists all past uploads with status and counts."""
    offset = (page - 1) * per_page
    resp = (
        supabase.table("uploads")
        .select("*")
        .order("created_at", desc=True)
        .range(offset, offset + per_page - 1)
        .execute()
    )
    return {"data": resp.data or [], "page": page, "per_page": per_page}
