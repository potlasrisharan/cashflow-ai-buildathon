import re
from fastapi import HTTPException


MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def month_bounds(month: str) -> tuple[str, str]:
    """
    Convert YYYY-MM into [start_date, end_date) bounds.
    """
    if not MONTH_PATTERN.match(month):
        raise HTTPException(
            status_code=422,
            detail="Invalid month format. Expected YYYY-MM.",
        )

    year, month_num = [int(part) for part in month.split("-")]
    if month_num == 12:
        next_month = f"{year + 1}-01"
    else:
        next_month = f"{year}-{month_num + 1:02d}"

    start = f"{month}-01"
    end = f"{next_month}-01"
    return start, end
