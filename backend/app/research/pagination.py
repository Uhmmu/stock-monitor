from datetime import date

from .enums import ResearchErrorCode
from .exceptions import ResearchError

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_DATE_SPAN_DAYS = 3660


def page_window(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ResearchError(ResearchErrorCode.invalid_parameter, f"page must be >= 1 and page_size <= {MAX_PAGE_SIZE}", field="page_size", status_code=422)
    return (page - 1) * page_size, page_size


def validate_date_range(start_date: date | None, end_date: date | None, *, max_days: int = MAX_DATE_SPAN_DAYS) -> None:
    if start_date and end_date:
        if start_date > end_date:
            raise ResearchError(ResearchErrorCode.invalid_date_range, "start_date must not be after end_date", field="start_date", status_code=422)
        if (end_date - start_date).days > max_days:
            raise ResearchError(ResearchErrorCode.invalid_date_range, f"date range exceeds {max_days} days", field="end_date", status_code=422)

