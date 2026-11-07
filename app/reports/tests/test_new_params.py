from urllib.parse import urlencode

from django.http import QueryDict

from reports.filters import Filters, describe, parse_filters, to_query

RULES = '{"op":"and","items":[{"c":"age","o":"gte","v":"30"}]}'
MARKS = '[{"c":"salary","o":"gt","v":"1000","k":"red"}]'


def _query(pairs: list[tuple[str, str]]) -> str:
    return urlencode(pairs)


def test_round_trip_of_the_new_parameters() -> None:
    raw = _query(
        [
            ("sort", "department,-salary"),
            ("group", "department,position"),
            ("pin", "2"),
            ("totals", "salary:sum"),
            ("rules", RULES),
        ]
    )
    # to_query emits group before sort, then rules, totals, marks, pin: the cleaned query is in that order
    cleaned = _query(
        [
            ("group", "department,position"),
            ("sort", "department,-salary"),
            ("rules", RULES),
            ("totals", "salary:sum"),
            ("pin", "2"),
        ]
    )
    assert to_query(parse_filters(QueryDict(raw))) == cleaned


def test_marks_round_trip() -> None:
    raw = _query([("marks", MARKS)])
    assert to_query(parse_filters(QueryDict(raw))) == raw


def test_lone_surrogate_in_rules_does_not_raise_in_to_query() -> None:
    # a JSON escape for a lone surrogate: json.loads gives a str that urlencode cannot write as UTF-8
    crafted = '{"op":"and","items":[{"c":"a","o":"contains","v":"\\ud800"}]}'
    raw = _query([("rules", crafted)])
    filters = parse_filters(QueryDict(raw))
    assert filters.rules == ""
    assert to_query(filters) == ""


def test_pin_is_read_as_0_to_3() -> None:
    assert parse_filters(QueryDict("pin=2")).pin == 2
    assert parse_filters(QueryDict("pin=99")).pin == 0
    assert parse_filters(QueryDict("pin=-1")).pin == 0
    assert parse_filters(QueryDict("pin=x")).pin == 0


def test_pin_zero_is_left_out_of_the_address() -> None:
    assert to_query(Filters(pin=0)) == ""
    assert to_query(Filters(pin=3)) == "pin=3"


def test_five_sort_keys_are_kept() -> None:
    assert parse_filters(QueryDict("sort=a,b,c,d,e")).sort == "a,b,c,d,e"


def test_six_sort_keys_give_empty() -> None:
    assert parse_filters(QueryDict("sort=a,b,c,d,e,f")).sort == ""


def test_four_group_keys_give_empty() -> None:
    assert parse_filters(QueryDict("group=a,b,c,d")).group == ""


def test_three_group_keys_are_kept() -> None:
    assert parse_filters(QueryDict("group=a,b,c")).group == "a,b,c"


def test_repeated_key_is_dropped() -> None:
    assert parse_filters(QueryDict("sort=department,-department,salary")).sort == "department,salary"
    assert parse_filters(QueryDict("group=department,department")).group == "department"


def test_bad_sort_or_group_part_gives_empty() -> None:
    assert parse_filters(QueryDict("sort=department,Salary")).sort == ""
    assert parse_filters(QueryDict("sort=department,,salary")).sort == ""
    assert parse_filters(QueryDict("sort=--x,a")).sort == ""
    assert parse_filters(QueryDict("group=department,-salary")).group == ""
    assert parse_filters(QueryDict("group=department,a1")).group == ""


def test_sort_key_over_40_characters_gives_empty() -> None:
    assert parse_filters(QueryDict("sort=" + "a" * 41)).sort == ""


def test_garbage_rules_totals_marks_give_empty() -> None:
    f = parse_filters(QueryDict("rules=garbage&totals=salary:median&marks=nope"))
    assert (f.rules, f.totals, f.marks) == ("", "", "")


def test_oversize_rules_give_empty() -> None:
    f = parse_filters(QueryDict(_query([("rules", "a" * 3000)])))
    assert f.rules == ""


def test_valid_rules_are_stored_in_canonical_form() -> None:
    spaced = '{ "op": "and", "items": [ { "c": "age", "o": "gte", "v": "30" } ] }'
    assert parse_filters(QueryDict(_query([("rules", spaced)]))).rules == RULES


def test_old_addresses_are_unchanged() -> None:
    assert to_query(parse_filters(QueryDict("sort=-name&group=department"))) == "group=department&sort=-name"


def test_describe_names_the_rules_with_labels() -> None:
    f = Filters(rules=RULES)
    assert describe(f, (), labels={"age": "Нас"}) == ["Нөхцөл: Нас ≥ 30"]


def test_describe_falls_back_to_the_column_key_without_labels() -> None:
    assert describe(Filters(rules=RULES), ()) == ["Нөхцөл: age ≥ 30"]


def test_describe_without_rules_has_no_rules_line() -> None:
    assert describe(Filters(), ()) == []
    assert not any(line.startswith("Нөхцөл:") for line in describe(Filters(), ("state",)))
