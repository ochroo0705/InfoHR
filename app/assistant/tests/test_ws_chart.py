from decimal import Decimal

import pytest

from assistant.ws_chart import (
    DEFAULT_TOP_N,
    OTHER_LABEL,
    ChartSpec,
    build_payload,
    chart_spec_from_json,
    chart_spec_from_reply,
    chart_spec_to_json,
)

COLS = ("DEPT", "N", "SEX")
NAMES: dict[str, str] = {}


def test_valid_spec_roundtrips() -> None:
    s = ChartSpec("bar", "DEPT", ("N",))
    assert chart_spec_from_json(chart_spec_to_json(s), COLS) == s


def test_unknown_type_or_column_is_none() -> None:
    assert chart_spec_from_json('{"type":"radar","x":"DEPT","y":["N"]}', COLS) is None
    assert chart_spec_from_json('{"type":"bar","x":"NOPE","y":["N"]}', COLS) is None
    assert chart_spec_from_json('{"type":"bar","x":"DEPT","y":[]}', COLS) is None
    assert chart_spec_from_json("not json", COLS) is None
    assert chart_spec_from_json("", COLS) is None


def test_lowercase_columns_resolve() -> None:
    spec = chart_spec_from_json('{"type":"bar","x":"dept","y":["n"]}', COLS)
    assert spec is not None
    assert spec.x == "DEPT"
    assert spec.y == ("N",)


def test_top_n_clamped() -> None:
    high = chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"top_n":99}', COLS)
    low = chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"top_n":-1}', COLS)
    assert high is not None and high.top_n == 30
    assert low is not None and low.top_n == DEFAULT_TOP_N


def test_bool_top_n_is_default() -> None:
    spec = chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"top_n":true}', COLS)
    assert spec is not None and spec.top_n == DEFAULT_TOP_N


def test_missing_or_unknown_sort_is_none_value() -> None:
    spec = chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"]}', COLS)
    assert spec is not None and spec.sort == "none"
    spec = chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"sort":"random"}', COLS)
    assert spec is not None and spec.sort == "none"


def test_reply_none_means_remove() -> None:
    assert chart_spec_from_reply({"type": "none"}, COLS) == "none"


def test_reply_garbage_is_none() -> None:
    assert chart_spec_from_reply("bar", COLS) is None
    assert chart_spec_from_reply(None, COLS) is None


def test_payload_bar() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    payload = build_payload(spec, COLS, [("A", 3, ""), ("B", 5, "")], NAMES)
    assert payload == {
        "kind": "bar",
        "labels": ["A", "B"],
        "values": [3.0, 5.0],
        "money": False,
        "percent": False,
        "value_label": "N",
        "series": [],
        "hrefs": [],
    }


def test_payload_value_label_uses_names() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    payload = build_payload(spec, COLS, [("A", 3, "")], {"N": "Headcount"})
    assert payload is not None and payload["value_label"] == "Headcount"


@pytest.mark.parametrize(
    ("chart_type", "kind"),
    [
        ("bar", "bar"),
        ("hbar", "hbar"),
        ("stacked_bar", "stacked"),
        ("line", "line"),
        ("area", "area"),
        ("donut", "donut"),
        ("pie", "pie"),
    ],
)
def test_payload_kind_mapping(chart_type: str, kind: str) -> None:
    spec = ChartSpec(chart_type, "DEPT", ("N",), series_by="SEX" if chart_type == "stacked_bar" else "")
    payload = build_payload(spec, COLS, [("A", 1, "M")], NAMES)
    assert payload is not None and payload["kind"] == kind


def test_short_or_bad_rows_skipped() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    payload = build_payload(spec, COLS, [None, ("A",), ("B", 2, "")], NAMES)  # type: ignore[list-item]
    assert payload is not None and payload["labels"] == ["B"]


def test_x_in_y_rejected() -> None:
    assert chart_spec_from_json('{"type":"bar","x":"DEPT","y":["DEPT"]}', COLS) is None
    assert chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"series_by":"DEPT"}', COLS) is None
    assert chart_spec_from_json('{"type":"bar","x":"DEPT","y":["N"],"series_by":"N"}', COLS) is None


def test_area_never_folds_even_sorted() -> None:
    rows = [(f"P{i}", i, "") for i in range(20)]
    spec = ChartSpec("area", "DEPT", ("N",), sort="value_desc", top_n=12)
    payload = build_payload(spec, COLS, rows, NAMES)
    assert payload is not None
    assert len(payload["labels"]) == 20
    assert OTHER_LABEL not in payload["labels"]


def test_multi_y_one_series_each() -> None:
    spec = ChartSpec("bar", "DEPT", ("N", "M"))
    payload = build_payload(spec, ("DEPT", "N", "M"), [("A", 1, 2), ("B", 3, 4)], {"N": "Headcount", "M": "Men"})
    assert payload is not None
    assert [s["label"] for s in payload["series"]] == ["Headcount", "Men"]
    assert payload["series"][1]["values"] == [2.0, 4.0]


def test_payload_folds_other() -> None:
    rows = [(f"D{i}", i, "") for i in range(40)]
    spec = ChartSpec("bar", "DEPT", ("N",), sort="value_desc", top_n=12)
    payload = build_payload(spec, COLS, rows, NAMES)
    assert payload is not None
    assert len(payload["labels"]) == 13
    assert payload["labels"][-1] == OTHER_LABEL
    assert payload["values"][-1] == float(sum(range(28)))


def test_payload_series_by() -> None:
    spec = ChartSpec("stacked_bar", "DEPT", ("N",), series_by="SEX")
    rows = [("A", 2, "M"), ("A", 1, "F"), ("B", 4, "M")]
    payload = build_payload(spec, COLS, rows, NAMES)
    assert payload is not None
    assert payload["labels"] == ["A", "B"]
    assert payload["series"] == [
        {"label": "M", "values": [2.0, 4.0]},
        {"label": "F", "values": [1.0, None]},
    ]


def test_text_y_column_gives_none() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    assert build_payload(spec, COLS, [("A", "abc", ""), ("B", "abc", "")], NAMES) is None


def test_null_value_stays_null() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    payload = build_payload(spec, COLS, [("A", None, "")], NAMES)
    assert payload is not None and payload["values"] == [None]


def test_decimal_values_become_floats() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    payload = build_payload(spec, COLS, [("A", Decimal("2.5"), "")], NAMES)
    assert payload is not None and payload["values"] == [2.5]


def test_line_never_folds() -> None:
    months = [f"{2025 + i // 12}-{i % 12 + 1:02d}" for i in range(24)]
    rows = [(month, i + 1, "") for i, month in enumerate(months)]
    spec = ChartSpec("line", "DEPT", ("N",), sort="none", top_n=12)
    payload = build_payload(spec, COLS, rows, NAMES)
    assert payload is not None
    assert payload["labels"] == months
    assert OTHER_LABEL not in payload["labels"]
    assert len(payload["labels"]) == 24


def test_empty_rows_none() -> None:
    spec = ChartSpec("bar", "DEPT", ("N",))
    assert build_payload(spec, COLS, [], NAMES) is None


def test_top_n_zero_folds_for_bars() -> None:
    # 0 means no folding only for a time series; a bar gets the default top count and the rest folds into «Бусад».
    rows = [(f"D{i}", i, "") for i in range(40)]
    for chart_type in ("bar", "hbar", "stacked_bar", "donut", "pie"):
        spec = ChartSpec(chart_type, "DEPT", ("N",), sort="value_desc", top_n=0)
        payload = build_payload(spec, COLS, rows, NAMES)
        assert payload is not None
        assert len(payload["labels"]) == 13, chart_type
        assert payload["labels"][-1] == OTHER_LABEL, chart_type


def test_top_n_zero_never_folds_a_line() -> None:
    rows = [(f"D{i}", i, "") for i in range(40)]
    spec = ChartSpec("line", "DEPT", ("N",), sort="none", top_n=0)
    payload = build_payload(spec, COLS, rows, NAMES)
    assert payload is not None
    assert len(payload["labels"]) == 40
    assert OTHER_LABEL not in payload["labels"]
