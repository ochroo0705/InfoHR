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


def test_note_names_the_columns_by_label_and_shows_no_sql() -> None:
    new = "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1"
    labels = {"HIRE_DATE": "Ажилд орсон огноо"}
    note = dropped_note(OLD, new, 35, 68, labels)
    assert "(Ажилд орсон огноо)" in note
    assert "Буцаах" in note
    assert "HIRE_DATE" not in note and "SELECT" not in note and "DATEADD" not in note


def test_note_without_a_label_says_only_that_a_filter_may_be_gone() -> None:
    new = "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1"
    note = dropped_note(OLD, new, 35, 68, {})
    assert "нэг нь" in note and "(" not in note
    assert "EXISTS" not in note.upper()


def test_refine_prompt_says_add_means_widen_and_keep_the_group() -> None:
    from assistant.sqlask import REFINE_INSTRUCTION

    assert "нэмж харуул" in REFINE_INSTRUCTION
    assert "OR inside ONE parenthesis" in REFINE_INSTRUCTION
    assert "never over the whole table" in REFINE_INSTRUCTION


def test_or_widening_that_keeps_the_old_selection_is_not_flagged() -> None:
    old = (
        "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1 AND E.DEPARTMENT_NAME = 'A' "
        "AND E.HIRE_DATE = (SELECT MIN(E2.HIRE_DATE) FROM GOV_EMPLOYEES AS E2 WHERE E2.DEPARTMENT_NAME = 'A')"
    )
    new = (
        "SELECT E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.WORKING = 1 AND E.DEPARTMENT_NAME = 'A' "
        "AND (E.HIRE_DATE = (SELECT MIN(E2.HIRE_DATE) FROM GOV_EMPLOYEES AS E2 WHERE E2.DEPARTMENT_NAME = 'A') "
        "OR E.HIRE_DATE = (SELECT MAX(E3.HIRE_DATE) FROM GOV_EMPLOYEES AS E3 WHERE E3.DEPARTMENT_NAME = 'A'))"
    )
    assert dropped_note(old, new, 1, 2) == ""
    replaced = new.replace("E.HIRE_DATE = (SELECT MIN", "E.HIRE_DATE = (SELECT MAX", 1)
    replaced = replaced.replace(" AND E.DEPARTMENT_NAME = 'A'", "", 1)
    assert dropped_note(old, replaced, 1, 1) != ""  # a lost department filter is still named


def test_refine_prompt_keeps_what_this_department_points_at() -> None:
    from assistant.sqlask import REFINE_INSTRUCTION

    assert "«энэ хэлтэс»" in REFINE_INSTRUCTION
    assert "choose them again with a sub-query" in REFINE_INSTRUCTION
    assert "each department" in REFINE_INSTRUCTION


def test_dropped_first_n_is_noted_when_the_result_grew() -> None:
    from assistant.ws_kept import dropped_row_limit

    top = "SELECT FIRST 1 DEPARTMENT_NAME, AVG(X) AS A FROM GOV_EMPLOYEES GROUP BY DEPARTMENT_NAME ORDER BY A DESC"
    each = (
        "SELECT E.DEPARTMENT_NAME, E.LAST_NAME FROM GOV_EMPLOYEES AS E WHERE E.HIRE_DATE = "
        "(SELECT MIN(E2.HIRE_DATE) FROM GOV_EMPLOYEES AS E2 WHERE E2.DEPARTMENT_NAME = E.DEPARTMENT_NAME)"
    )
    kept = "SELECT FIRST 1 DEPARTMENT_NAME, LAST_NAME FROM GOV_EMPLOYEES ORDER BY HIRE_DATE"
    assert dropped_row_limit(top, each)
    assert not dropped_row_limit(top, kept)
    assert not dropped_row_limit(each, top)
    assert not dropped_row_limit("not sql (", each)
    note = dropped_note(top, each, 1, 20)
    assert "эхний мөр" in note and "Буцаах" in note
    assert "FIRST" not in note and "SELECT" not in note
    assert dropped_note(top, each, 20, 1) == ""  # a narrower result is not flagged


def test_refined_line_is_plain_words() -> None:
    from assistant.ws_service import refined_line

    assert refined_line(1, 1) == "Хүснэгтийг шинэчиллээ: 1 мөр хэвээр байна."
    assert refined_line(98, 12) == "Хүснэгтийг шинэчиллээ: 98 мөр байсан, одоо 12 мөр байна."
    assert "→" not in refined_line(3, 5)


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


def test_prompt_groups_a_person_with_their_records() -> None:
    from assistant.sqlask import _system

    text = _system("catalogue", ())
    assert "ажилчдыг хүүхдүүдтэй нь" in text
    assert "set group_by to EMP_ID" in text
    assert "ONE ROW PER RECORD" in text


def test_a_refine_case_can_name_the_group_it_expects() -> None:
    from assistant.sqleval import REFINE_CASES

    grouped = [case for case in REFINE_CASES if case.group]
    assert grouped and all(case.group == case.group.upper() for case in grouped)


def test_a_query_naming_a_child_cannot_become_an_approved_example() -> None:
    from assistant.admin import _names_a_person

    assert _names_a_person("SELECT EMP_ID FROM GOV_CHILDREN WHERE CHILD_NAME = 'Анхбаяр'")
    assert _names_a_person("SELECT EMP_ID FROM GOV_CHILDREN WHERE CHILD_SURNAME LIKE 'Сүр%'")
    assert not _names_a_person("SELECT EMP_ID, CHILD_NAME FROM GOV_CHILDREN WHERE GENDER = 'F'")


def test_top_n_ascending_sort_puts_empty_values_last() -> None:
    from assistant.sqlask import nulls_last_under_first

    first = nulls_last_under_first("SELECT FIRST 1 E.LAST_NAME FROM GOV_EMPLOYEES AS E ORDER BY E.HIRE_DATE")
    assert "ORDER BY E.HIRE_DATE NULLS LAST" in first and first.upper().count("NULLS") == 1
    mixed = nulls_last_under_first("SELECT FIRST 3 A FROM T ORDER BY B ASC, C DESC")
    assert "B ASC NULLS LAST" in mixed and "C DESC" in mixed and "C DESC NULLS" not in mixed
    inner = nulls_last_under_first("SELECT X FROM T WHERE D = (SELECT FIRST 1 D FROM T ORDER BY D)")
    assert "ORDER BY D NULLS LAST" in inner


def test_nulls_last_leaves_other_queries_alone() -> None:
    from assistant.sqlask import nulls_last_under_first

    plain = "SELECT A FROM T ORDER BY B"  # no limit: a plain sorted list keeps its order
    assert nulls_last_under_first(plain) == plain
    desc = "SELECT FIRST 1 A FROM T ORDER BY B DESC"
    assert nulls_last_under_first(desc) == desc
    assert nulls_last_under_first("SELECT FIRST 1 A FROM T") == "SELECT FIRST 1 A FROM T"
    garbage = "SELECT FIRST ORDER BY ((("
    assert nulls_last_under_first(garbage) == garbage
    again = nulls_last_under_first("SELECT FIRST 1 A FROM T ORDER BY B NULLS LAST")
    assert again.upper().count("NULLS LAST") == 1  # already last: not doubled

