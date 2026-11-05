"""HelpEntry: fixed URL arguments and the person-bound marker."""

from datetime import date

from django.urls import reverse

from assistant.entry import HelpEntry


def _entry(**extra: object) -> HelpEntry:
    base: dict[str, object] = {
        "key": "test.entry",
        "title": "Тест",
        "steps": ("Тест.",),
        "url_name": "leave:balances",
        "modal": False,
        "need": lambda user, day: True,
        "labels": (),
    }
    base.update(extra)
    return HelpEntry(**base)  # type: ignore[arg-type]


def test_url_uses_fixed_args() -> None:
    entry = _entry(url_name="reports:report", url_args=("staff-list",))
    assert entry.url() == "/reports/staff-list/"


def test_url_without_args() -> None:
    assert _entry().url() == reverse("leave:balances")


def test_person_url_with_tab() -> None:
    entry = _entry(person_tab="personal")
    assert entry.person_url(5) == reverse("employees:detail", args=[5]) + "#personal"


def test_person_url_plain() -> None:
    entry = _entry(person_tab="")
    assert entry.person_url(5) == reverse("employees:detail", args=[5])
    assert "#" not in entry.person_url(5)


def test_not_person_by_default() -> None:
    assert _entry().person is False
    assert _entry(person_tab="").person is True
    assert _entry(person_tab="salary").person is True


def test_need_is_called_with_user_and_day() -> None:
    seen: list[date] = []

    def need(user: object, day: date) -> bool:
        seen.append(day)
        return True

    entry = _entry(need=need)
    assert entry.need(None, date(2026, 11, 5))  # type: ignore[arg-type]
    assert seen == [date(2026, 11, 5)]
