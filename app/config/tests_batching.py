"""The batch slices of config.batching: the request-free batch_at, and window (which must read the same slice from a
request and keep its query parameters)."""

from urllib.parse import parse_qs

from django.test import RequestFactory

from config import batching


def test_batch_at_gives_the_first_batch_and_the_next_offset() -> None:
    items = list(range(130))
    batch = batching.batch_at(items, 0)
    assert batch.shown == items[:60]
    assert batch.offset == 0
    assert batch.next_query == "offset=60"


def test_batch_at_last_batch_has_no_next_query() -> None:
    batch = batching.batch_at(list(range(130)), 120)
    assert batch.shown == list(range(120, 130))
    assert batch.offset == 120
    assert batch.next_query == ""


def test_batch_at_honours_its_size() -> None:
    batch = batching.batch_at(list(range(5)), 2, 2)
    assert batch.shown == [2, 3]
    assert batch.next_query == "offset=4"


def test_window_keeps_its_slice_and_query_parameters() -> None:
    request = RequestFactory().get("/x/", {"offset": "60", "q": "a"}, HTTP_HX_REQUEST="true")
    batch = batching.window(request, list(range(130)))
    assert batch.shown == list(range(60, 120))
    assert batch.offset == 60
    assert parse_qs(batch.next_query) == {"offset": ["120"], "q": ["a"]}


def test_window_without_htmx_starts_at_zero() -> None:
    request = RequestFactory().get("/x/", {"offset": "60"})
    batch = batching.window(request, list(range(130)))
    assert batch.offset == 0
    assert batch.shown == list(range(60))


def test_window_junk_offset_starts_at_zero() -> None:
    for raw in ("-1", "²", "1e3"):
        request = RequestFactory().get("/x/", {"offset": raw}, HTTP_HX_REQUEST="true")
        assert batching.window(request, list(range(130))).offset == 0
