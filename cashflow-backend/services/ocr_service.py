"""
OCR.space receipt parsing service.
Accepts image bytes → returns extracted vendor, amount, date, line items.
"""
import re
import httpx
import base64
from typing import Any

from config import settings

OCR_URL = "https://api.ocr.space/parse/image"


async def extract_receipt_data(
    image_bytes: bytes,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    """
    Send image to OCR.space API.
    Parse the full text to extract:
    - vendor name
    - total amount
    - date
    - individual line items (best effort)
    """
    # Encode to base64 for OCR.space base64 endpoint
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_uri = f"data:{content_type};base64,{b64}"

    payload = {
        "apikey":         settings.OCR_SPACE_API_KEY,
        "base64Image":    data_uri,
        "language":       "eng",
        "isOverlayRequired": False,
        "detectOrientation": True,
        "scale":          True,
        "OCREngine":      2,   # Engine 2 is better for receipts
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(OCR_URL, data=payload)
        resp.raise_for_status()
        result = resp.json()

    if result.get("IsErroredOnProcessing"):
        error_msg = result.get("ErrorMessage", ["Unknown OCR error"])
        raise RuntimeError(f"OCR.space error: {error_msg}")

    # Extract raw text
    parsed_results = result.get("ParsedResults", [])
    if not parsed_results:
        return {"raw_text": "", "vendor": None, "amount": None, "date": None, "line_items": []}

    # Preserve line structure for downstream line-item/date parsing.
    raw_text = "\n".join(p.get("ParsedText", "") for p in parsed_results)

    return _parse_receipt_text(raw_text)


def _parse_receipt_text(text: str) -> dict[str, Any]:
    """
    Heuristic parser for common receipt formats.
    Extracts vendor, total amount, date and line items.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # ── Vendor: first non-empty line is usually the merchant name ─
    vendor = lines[0] if lines else None

    # ── Amount: look for "Total", "Grand Total", "TOTAL" patterns ─
    amount = None
    amount_patterns = [
        r"(?:grand\s+)?total[:\s]+(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)",
        r"(?:amount\s+due|to\s+pay)[:\s]+(?:rs\.?|inr|₹)?\s*([\d,]+\.?\d*)",
        r"(?:rs\.?|inr|₹)\s*([\d,]+\.?\d*)\s*$",
    ]
    for pat in amount_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            raw_amt = match.group(1).replace(",", "")
            try:
                amount = float(raw_amt)
                break
            except ValueError:
                continue

    # If no labeled total, grab the largest currency amount in text
    if amount is None:
        all_amounts = re.findall(r"(?:rs\.?|inr|₹)?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        if all_amounts:
            try:
                amount = max(float(a.replace(",", "")) for a in all_amounts)
            except ValueError:
                pass

    # ── Date: common date patterns ─────────────────────────────
    date = None
    date_patterns = [
        r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
        r"(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})",
    ]
    for pat in date_patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            date = match.group(1)
            break

    # ── Line items: lines with a price at the end ───────────────
    line_items = []
    item_pat = re.compile(r"^(.+?)\s+(?:rs\.?|₹)?\s*([\d,]+\.?\d*)\s*$", re.IGNORECASE)
    for line in lines[1:]:
        m = item_pat.match(line)
        if m:
            desc = m.group(1).strip()
            try:
                price = float(m.group(2).replace(",", ""))
                if desc and price > 0:
                    line_items.append({"description": desc, "amount": price})
            except ValueError:
                pass

    return {
        "vendor":     vendor,
        "amount":     amount,
        "date":       date,
        "line_items": line_items[:20],  # cap at 20 items
        "raw_text":   text[:2000],      # first 2000 chars for debug
    }
