"""The folded plain-text copy of a log entry's changes (`logs.foldtext`): the fold rule, the text, the limit."""

from typing import Any

from employees.palette import _fold

from logs.foldtext import CHANGE_TEXT_LIMIT, change_text, fold


def test_fold_matches_the_palette_rule() -> None:
    assert fold("Сүхбаатар") == "сухбаатар"
    assert _fold("Сүхбаатар") == fold("Сүхбаатар")


def test_change_text_has_field_old_and_new_folded() -> None:
    text = change_text([{"field": "Хаяг", "old": "Сүхбаатар", "new": "Баянзүрх"}])
    assert text == "хаяг сухбаатар баянзурх"


def test_change_text_handles_none_numbers_and_missing_keys() -> None:
    changes: list[dict[str, object]] = [
        {"field": "Цалин", "old": None, "new": 1500000},
        {"field": "Хэлтэс"},
        {"old": "Нягтлан", "new": None},
    ]
    assert change_text(changes) == "цалин 1500000 хэлтэс нягтлан"


def test_change_text_is_cut_to_the_limit() -> None:
    changes: list[dict[str, object]] = [{"field": "Тэмдэглэл", "old": "а" * 50000, "new": "б"}]
    text = change_text(changes)
    assert len(text) == CHANGE_TEXT_LIMIT == 20000
    assert text.startswith("тэмдэглэл ")
    assert len(change_text(changes, limit=50)) == 50


def test_change_text_skips_entries_that_are_not_dicts() -> None:
    changes: list[Any] = ["junk", None, 5, ["Хаяг"], {"field": "Цалин", "new": 1}]
    assert change_text(changes) == "цалин 1"


def test_change_text_reads_a_changes_value_that_is_not_a_list_as_nothing() -> None:
    not_lists: list[Any] = [{"field": "Цалин", "new": 1}, "Цалин", 7, None]
    for value in not_lists:
        assert change_text(value) == "", value
