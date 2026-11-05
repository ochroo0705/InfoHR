import dataclasses

from assistant.entries import ENTRIES
from assistant.entry import HelpEntry
from assistant.matching import covers, narrow_entries, only_generic, word_forms


def test_only_generic_text() -> None:
    assert only_generic("хэлтэс") is True
    assert only_generic("Газрын алба") is True
    assert only_generic("") is True
    assert only_generic("Санхүү хэлтэс") is False
    assert only_generic("Санхүү") is False


def test_word_forms_folds_and_strips_endings() -> None:
    forms = word_forms("Санхүүгийн хэлтсийн")
    assert len(forms) == 1
    assert {"санхуу", "санхуугийн"} <= forms[0]


def test_word_forms_drops_generic_words() -> None:
    # a generic word in a phrase with other words is left out, for each of the nine forms
    for generic in ("хэлтсийн", "хэлтэс", "алба", "албаны", "газар", "газрын", "салбар", "салбарын", "тасаг"):
        forms = word_forms(f"Санхүү {generic}")
        assert len(forms) == 1, generic
        assert "санхуу" in forms[0], generic


def test_word_forms_keeps_text_of_only_generic_words() -> None:
    assert len(word_forms("Газрын")) == 1
    assert len(word_forms("хэлтсийн")) == 1


def test_word_forms_keeps_words_that_only_start_like_generic() -> None:
    # «албан» (position word) is not the generic «алба»: its one-letter ending «н» does not count for the generic check
    assert word_forms("албан тушаал") == [{"албан", "алба"}, {"тушаал"}]


def test_covers_prefix_and_exact() -> None:
    assert covers(word_forms("санхүү"), "Санхүүгийн хэлтэс") is True
    assert covers(word_forms("маркетинг"), "Санхүү") is False


def test_covers_genitive_phrase_matches_stem_name() -> None:
    assert covers(word_forms("санхүүгийн"), "Санхүү") is True


def test_covers_needs_every_phrase_word() -> None:
    assert covers(word_forms("санхүү маркетинг"), "Санхүү") is False
    assert covers(word_forms("санхүү маркетинг"), "Санхүүгийн маркетингийн хэлтэс") is True


def test_covers_short_stem_never_matches() -> None:
    assert covers(word_forms("ий"), "Санхүүгийн хэлтэс") is False
    assert covers(word_forms("ий"), "ий") is False


def test_covers_generic_only_phrase_is_literal() -> None:
    # a phrase of only a generic word is kept as it is, so it is compared with the name like any other word
    assert covers(word_forms("хэлтэс"), "Санхүүгийн хэлтэс") is True
    assert covers(word_forms("хэлтэс"), "Санхүү") is False


def test_covers_surname_equal_to_generic_word() -> None:
    assert covers(word_forms("Газрын"), "Газрын Баяр") is True


def test_covers_upper_case_and_o_u_variants() -> None:
    assert covers(word_forms("САНХҮҮГИЙН"), "Санхүү") is True
    assert covers(word_forms("санхуугийн"), "Санхүү") is True


def test_narrow_returns_all_when_few() -> None:
    entries = list(ENTRIES[:10])
    assert narrow_entries("амралт бүртгэх", entries, limit=15) == entries


def _fake_entries() -> list[HelpEntry]:
    base = ENTRIES[0]
    fakes = [
        dataclasses.replace(base, key=f"fake.{i}", title=f"Дэлгэц {i}", words=(f"үг{i}",), examples=(), learned=())
        for i in range(29)
    ]
    target = dataclasses.replace(
        base, key="fake.leave", title="Чөлөөний дэлгэц", words=("амралт",), examples=(), learned=()
    )
    return [*fakes, target]


def test_narrow_keeps_entry_named_by_question() -> None:
    entries = _fake_entries()
    result = narrow_entries("амралт бүртгэх", entries, limit=15)
    assert "fake.leave" in [e.key for e in result]
    assert len(result) <= 15


def test_narrow_rare_word_outranks_many_common_ones() -> None:
    base = ENTRIES[0]
    common = [
        dataclasses.replace(base, key=f"common.{i}", title=f"Бүртгэл {i}", words=("бүртгэх",), examples=(), learned=())
        for i in range(16)
    ]
    rare = dataclasses.replace(base, key="rare.leave", title="Амралт", words=("амралт",), examples=(), learned=())
    result = narrow_entries("амралт бүртгэх", [*common, rare], limit=15)
    assert "rare.leave" in [e.key for e in result]
    assert len(result) <= 15


def test_narrow_no_overlap_returns_all() -> None:
    entries = _fake_entries()
    assert narrow_entries("огт өөр асуулт", entries, limit=15) == entries
