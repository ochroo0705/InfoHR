"""The dropped-condition note, the history that goes to the model and the first-line pin of the refine prompt."""

from datetime import date

from assistant.sqlask import REFINE_HISTORY_TURNS, _refine_user
from assistant.ws_kept import dropped_conditions
from assistant.ws_service import (
    DROPPED_NOTE,
    PROVIDER_LINE,
    REFINED_TEXT,
    dropped_note,
    failed_turns_removed,
)

OLD = (
    "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1 AND E.HIRE_DATE <= DATEADD(YEAR, -5, "
    "CAST('TODAY' AS TIMESTAMP)) AND NOT EXISTS(SELECT 1 FROM GOV_LEAVE AS L WHERE L.EMP_ID = E.EMP_ID) ORDER BY 1"
)


def test_added_column_with_the_filter_kept_loses_nothing() -> None:
    new = (
        "SELECT E.LAST_NAME, 1 AS X FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1 AND E.HIRE_DATE <= "
        "DATEADD(YEAR, -5, CURRENT_DATE) AND NOT EXISTS(SELECT 1 FROM GOV_LEAVE AS L WHERE L.EMP_ID = E.EMP_ID)"
    )
    assert dropped_conditions(OLD, new) == []


def test_filter_turned_into_a_column_is_named() -> None:
    new = (
        "SELECT E.LAST_NAME, CASE WHEN EXISTS(SELECT 1 FROM GOV_LEAVE AS L WHERE L.EMP_ID = E.EMP_ID) THEN 1 ELSE 0 "
        "END AS TAKEN FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1 AND E.HIRE_DATE <= DATEADD(YEAR, -5, CURRENT_DATE)"
    )
    gone = dropped_conditions(OLD, new)
    assert len(gone) == 1 and "NOT EXISTS" in gone[0].upper()


def test_unreadable_sql_gives_no_answer() -> None:
    assert dropped_conditions("not sql at all (", OLD) == []
    assert dropped_conditions("SELECT 1 FROM GOV_EMPLOYEES", OLD) == []  # no WHERE, nothing to lose


def test_note_is_skipped_when_the_result_got_narrower() -> None:
    new = "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1"
    assert dropped_note(OLD, new, 35, 20) == ""
    assert dropped_note(OLD, new, 35, 68).startswith(DROPPED_NOTE)
    assert dropped_note(OLD, new, None, None).startswith(DROPPED_NOTE)


def test_failed_exchange_is_left_out_of_the_history() -> None:
    messages = [
        ("user", "first"),
        ("assistant", REFINED_TEXT),
        ("user", "second"),
        ("assistant", PROVIDER_LINE),
        ("user", "second"),
        ("assistant", REFINED_TEXT),
    ]
    assert failed_turns_removed(messages) == [
        ("user", "first"),
        ("assistant", REFINED_TEXT),
        ("user", "second"),
        ("assistant", REFINED_TEXT),
    ]


def test_first_viewer_line_stays_in_the_prompt_of_a_long_tab() -> None:
    history = [("user", "THE FIRST QUESTION")] + [
        (role, f"line {n}") for n in range(REFINE_HISTORY_TURNS + 5) for role in ("assistant",)
    ]
    prompt = _refine_user("SELECT 1", ("A",), history, "next", date(2026, 11, 18), "")
    assert "user: THE FIRST QUESTION" in prompt
    assert f"line {REFINE_HISTORY_TURNS + 4}" in prompt
    short = _refine_user("SELECT 1", ("A",), history[-3:], "next", date(2026, 11, 18), "")
    assert "THE FIRST QUESTION" not in short  # nothing is added when the first line is not in the history at all
