"""Run the accuracy set through the provider for each role and print the score. Writes nothing to the database."""

import dataclasses
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from assistant import learning
from assistant.entries import ENTRY_BY_KEY, HelpEntry
from assistant.evalset import CASES, ROLE_ENTRIES, ROLES, EvalCase, expected
from assistant.providers import Provider, get_provider

OFF_MESSAGE = "Туслах идэвхгүй: .env-д ASSISTANT_* тохиргоо алга."


def _got(provider: Provider, case: EvalCase, entries: list[HelpEntry], refusals: tuple[str, ...], pause: float) -> str:
    """The key the service would keep: an entry outside the role's list counts as "" (as in answer())."""
    if not entries:
        return ""
    if pause > 0:  # spaces the calls out for providers with a requests-per-minute limit
        time.sleep(pause)
    try:
        choice = provider.choose(case.question, entries, refusals)
    except Exception:  # one bad call is a failed case, not the end of the run
        return "error"
    return choice.entry if choice.entry in {e.key for e in entries} else ""


class Command(BaseCommand):
    help = "Score the assistant on the accuracy set for each role. Writes nothing to the database."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--role", choices=ROLES, default=None, help="Only this role.")
        parser.add_argument(
            "--pause", type=float, default=0.0, help="Seconds to wait before each provider call (rate limits)."
        )
        parser.add_argument(
            "--shipped-only",
            action="store_true",
            help="Only the shipped cases: no local tests, and no learned examples sent to the provider.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        provider = get_provider()
        if provider is None:
            raise CommandError(OFF_MESSAGE)
        shipped_only = options["shipped_only"]
        tests = [] if shipped_only else learning.local_tests()
        cases = [*CASES, *(EvalCase(t.question, t.entry) for t in tests)]
        # Read once per run, as services.answer reads them once per question.
        learned: dict[str, tuple[str, ...]] = {} if shipped_only else learning.learned_by_entry()
        refusals: tuple[str, ...] = () if shipped_only else learning.no_entry_questions()

        header = f"Cases: shipped {len(CASES)}, local {len(tests)}"
        if tests:
            stamp = timezone.localtime(max(t.created_at for t in tests)).isoformat(timespec="seconds")
            header += f", newest {stamp}"
        self.stdout.write(header)

        roles = (options["role"],) if options["role"] else ROLES
        total = len(cases)
        total_passed = 0
        below_mark = False
        for role in roles:
            entries = [dataclasses.replace(ENTRY_BY_KEY[k], learned=learned.get(k, ())) for k in ROLE_ENTRIES[role]]
            passed = 0
            for case in cases:
                want = expected(case, role)
                got = _got(provider, case, entries, refusals, options["pause"])
                ok = got == want
                passed += ok
                status = "PASS" if ok else "FAIL"
                self.stdout.write(f"{status} {role} | {case.question} | expected {want or '-'} | got {got or '-'}")
            self.stdout.write(f"{role}: {passed}/{total}")
            total_passed += passed
            below_mark = below_mark or passed * 10 < total * 9  # the pass mark is 90%
        self.stdout.write(f"Overall: {total_passed}/{total * len(roles)}")
        if below_mark:
            raise CommandError("Pass mark not reached: every role needs at least 90%.")
