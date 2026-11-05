"""One help entry: a screen or action of the system the assistant can point to.

`url()` opens the screen. For a person-bound entry (`person_tab` is not None), `person_url(pk)` opens that employee's
page at the right tab.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from accounts.models import User
from django.urls import reverse


@dataclass(frozen=True)
class HelpEntry:
    key: str
    title: str
    steps: tuple[str, ...]
    url_name: str
    modal: bool
    need: Callable[[User, date], bool]
    labels: tuple[str, ...]  # every «…» label quoted in steps/note; the screens must show them
    words: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()
    note: str = ""
    learned: tuple[str, ...] = ()  # learned questions for this entry, filled per request; shipped entries keep it empty
    url_args: tuple[str, ...] = ()  # fixed reverse() args, e.g. ("staff-list",) for reports:report
    # None = not person-bound; "" = the employee page; otherwise the #tab of the employee page. Tab ids in
    # app/employees/templates/employees/detail.html: "work" (the default tab, no hash needed for ""),
    # "salary" (tab-salary, shown with can_view_salary), "personal" (tab-personal, shown with can_view_personal).
    person_tab: str | None = None

    def url(self) -> str:
        return reverse(self.url_name, args=self.url_args)

    def person_url(self, pk: int) -> str:
        url = reverse("employees:detail", args=[pk])
        return url + ("#" + self.person_tab if self.person_tab else "")

    @property
    def person(self) -> bool:
        return self.person_tab is not None
