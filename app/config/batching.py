"""Long lists that load in batches as the user scrolls (UI_RULES §picture cards: infinite scroll).

A view slices its rows with `window`; the page's `_more_batch.html` pill asks for the next slice (`?offset=`) when it
scrolls into view. The offset is read only from htmx requests, so a pasted link always opens the first batch.
"""

from collections.abc import Callable
from dataclasses import dataclass

from django.http import HttpRequest

LIST_BATCH = 60  # a multiple of 12 so card rows stay full at 1-4 columns


@dataclass
class Batch[T]:
    shown: list[T]
    offset: int  # 0 for the first batch
    next_query: str  # the query string of the next batch; "" when this is the last one


def window[T](request: HttpRequest, items: list[T], size: int | None = None) -> Batch[T]:
    size = size or LIST_BATCH  # read at call time so tests can shrink the batch
    raw = request.GET.get("offset", "")
    htmx = request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request")
    offset = int(raw) if htmx and raw.isdecimal() and len(raw) <= 18 else 0  # isdigit() accepts «²», int() does not
    next_query = ""
    if offset + size < len(items):
        params = request.GET.copy()
        params["offset"] = str(offset + size)
        next_query = params.urlencode()
    return Batch(items[offset : offset + size], offset, next_query)


def paged[T](
    request: HttpRequest, fetch: Callable[[int, int], tuple[list[T], bool]], size: int | None = None
) -> Batch[T]:
    """Like `window`, for a list the database slices itself: `fetch(offset, size)` returns that slice and whether
    more rows follow it, so the full list is never built (a register of thousands of rows)."""
    size = size or LIST_BATCH
    raw = request.GET.get("offset", "")
    htmx = request.headers.get("HX-Request") and not request.headers.get("HX-History-Restore-Request")
    offset = int(raw) if htmx and raw.isdecimal() and len(raw) <= 18 else 0  # isdigit() accepts «²», int() does not
    shown, more = fetch(offset, size)
    next_query = ""
    if more:
        params = request.GET.copy()
        params["offset"] = str(offset + size)
        next_query = params.urlencode()
    return Batch(shown, offset, next_query)
