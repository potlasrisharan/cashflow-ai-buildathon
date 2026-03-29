"""
POST /api/upload/csv       → Upload CSV of expenses → AI categorization + anomaly detection
POST /api/upload/receipt   → Upload receipt image → OCR → extract amount/vendor/date
GET  /api/upload/history   → List all uploads
"""
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
import io
import logging
import pandas as pd

from config import settings
from db import supabase
from services.ai_service import categorize_transactions
from services.ocr_service import extract_receipt_data
from services.anomaly_service import detect_anomalies

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Security limits ───────────────────────────────────────────────────────────
MAX_FILE_SIZE_BYTES = settings.max_upload_bytes
MAX_CSV_ROWS = 5000

ALLOWED_CSV_COLUMNS = {
    "date", "vendor", "amount", "department",
    "category", "payment_method", "invoice_no", "notes"
}
REQUIRED_CSV_COLUMNS = {"date", "vendor", "amount"}
ALLOWED_CSV_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",  # browsers sometimes label CSV as text/plain
}
ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/jpg", "application/pdf"}


def _is_probably_text(content: bytes) -> bool:
    if not content:
        return False
    sample = content[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            sample.decode("latin-1")
            return True
        except UnicodeDecodeError:
            return False


def _parse_amount(value: object) -> float:
    raw = str(value).strip().replace(",", "")
    return float(raw)


def _parse_date(value: object) -> str:
    parsed = pd.to_datetime(str(value).strip(), errors="coerce")
    if pd.isna(parsed):
        raise ValueError("invalid date")
    return parsed.date().isoformat()


def _validate_receipt_signature(content: bytes, content_type: str) -> None:
    if content_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Invalid PDF file.")

    if content_type in {"image/jpeg", "image/jpg"} and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=400, detail="Invalid JPEG file.")

    if content_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=400, detail="Invalid PNG file.")


@router.post("/csv")
async def upload_csv(file: UploadFile = File(...)):
    """
    Accepts a CSV file with at minimum: date, vendor, amount.
    - AI categorizes any row missing a category
    - Runs anomaly detection on all rows
    - Saves everything to Supabase
    """
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    if file.content_type and file.content_type.lower() not in ALLOWED_CSV_TYPES:
        raise HTTPException(status_code=400, detail="Invalid CSV content type.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {settings.MAX_UPLOAD_MB} MB.",
        )

    if not _is_probably_text(content):
        raise HTTPException(status_code=422, detail="CSV content appears to be binary or corrupted.")

    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception:
        raise HTTPException(status_code=422, detail="Could not parse CSV. Ensure valid CSV headers and values.")

    if df.empty:
        raise HTTPException(status_code=422, detail="CSV has no rows.")

    if len(df) > MAX_CSV_ROWS:
        raise HTTPException(status_code=413, detail=f"Too many rows. Maximum allowed rows: {MAX_CSV_ROWS}.")

    # Normalize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Alias mapping for easier processing
    aliases = {
        "description": "vendor",
        "merchant": "vendor",
        "payee": "vendor",
        "total": "amount",
    }
    for alias, target in aliases.items():
        if alias in df.columns and target not in df.columns:
            df.rename(columns={alias: target}, inplace=True)

    missing = REQUIRED_CSV_COLUMNS - set(df.columns)
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"CSV is missing required columns: {sorted(missing)}.",
        )

    unknown_cols = set(df.columns) - ALLOWED_CSV_COLUMNS
    if unknown_cols:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported columns present: {sorted(unknown_cols)}.",
        )

    df = df.where(pd.notnull(df), None)
    row_count = len(df)

    # Validate date/amount before sending any data to external AI services.
    invalid_core_rows: list[int] = []
    for idx, row in df.iterrows():
        try:
            parsed_amount = _parse_amount(row.get("amount", 0))
            if parsed_amount <= 0:
                raise ValueError("amount must be positive")
            _parse_date(row.get("date", ""))
        except Exception:
            invalid_core_rows.append(idx + 2)

    if invalid_core_rows:
        sample = ", ".join(str(x) for x in invalid_core_rows[:10])
        suffix = "..." if len(invalid_core_rows) > 10 else ""
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date/amount values in CSV rows: {sample}{suffix}",
        )

    # ── AI Categorization ─────────────────────────────────────
    needs_cat = df[df.get("category", pd.Series(dtype=str)).isna()] if "category" in df.columns else df
    categorized_count = 0

    if len(needs_cat) > 0:
        rows_for_ai = needs_cat[["vendor", "amount"]].to_dict("records")
        ai_results = await categorize_transactions(rows_for_ai)
        for idx, result in zip(needs_cat.index, ai_results):
            df.at[idx, "category"] = result.get("category", "Other")
            df.at[idx, "department"] = result.get("department", "Operations")
            df.at[idx, "ai_confidence"] = result.get("confidence", 0.75)
            categorized_count += 1
    else:
        categorized_count = row_count

    # ── Build validated transaction records ───────────────────
    records = []
    for idx, row in df.iterrows():
        txn_date = _parse_date(row.get("date", ""))
        amount = _parse_amount(row.get("amount", 0))

        records.append(
            {
                "date": txn_date,
                "vendor": str(row.get("vendor", "Unknown")).strip()[:200] or "Unknown",
                "category": str(row.get("category", "Other")).strip()[:80] or "Other",
                "department": str(row.get("department", "Operations")).strip()[:80] or "Operations",
                "amount": amount,
                "payment_method": str(row.get("payment_method", "Bank Transfer")).strip()[:80] or "Bank Transfer",
                "invoice_no": str(row.get("invoice_no", "")).strip()[:120] if row.get("invoice_no") else None,
                "notes": str(row.get("notes", "")).strip()[:500] if row.get("notes") else None,
                "status": "pending",
                "has_receipt": False,
                "ai_confidence": float(row.get("ai_confidence", 0.85)),
            }
        )

    if not records:
        raise HTTPException(status_code=422, detail="No valid rows were found in CSV.")

    inserted_ids: list[str] = []
    try:
        insert_resp = supabase.table("transactions").insert(records).execute()
        inserted_ids = [r["id"] for r in (insert_resp.data or [])]
        logger.info("upload_csv inserted %d transactions", len(inserted_ids))
    except Exception:
        logger.exception("upload_csv transaction insert failed")
        raise HTTPException(status_code=500, detail="Failed to save transactions.")

    # ── Anomaly Detection ─────────────────────────────────────
    flagged_count = 0
    if inserted_ids:
        try:
            anomalies = await detect_anomalies(records, inserted_ids)
            flagged_count = len(anomalies)
            if anomalies:
                supabase.table("anomalies").insert(anomalies).execute()
                logger.info("upload_csv logged %d anomalies", flagged_count)
        except Exception:
            logger.exception("upload_csv anomaly detection failed")

    # ── Log the upload ────────────────────────────────────────
    try:
        supabase.table("uploads").insert(
            {
                "filename": filename,
                "row_count": row_count,
                "categorized": categorized_count,
                "flagged": flagged_count,
                "status": "done",
            }
        ).execute()
    except Exception:
        logger.exception("upload_csv upload log insert failed")

    return {
        "status": "success",
        "filename": filename,
        "rows": row_count,
        "categorized": categorized_count,
        "flagged": flagged_count,
        "inserted_ids": inserted_ids,
    }


@router.post("/receipt")
async def upload_receipt(file: UploadFile = File(...)):
    """
    Accepts JPEG/PNG/PDF receipt files.
    Sends to OCR.space → extracts vendor, amount, date.
    Returns extracted data for user to confirm before saving.
    """
    filename = (file.filename or "").strip()
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_RECEIPT_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG/PNG/PDF files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {settings.MAX_UPLOAD_MB} MB.",
        )

    _validate_receipt_signature(content, content_type)

    try:
        extracted = await extract_receipt_data(content, filename, content_type)
    except Exception:
        logger.exception("upload_receipt OCR extraction failed")
        raise HTTPException(
            status_code=500,
            detail="Receipt extraction failed. Please upload a clearer file and try again.",
        )

    return {
        "status": "extracted",
        "filename": filename,
        "extracted": extracted,
        "preview": "Receipt parsed successfully. Review and confirm below.",
    }


@router.get("/history")
def upload_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
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
