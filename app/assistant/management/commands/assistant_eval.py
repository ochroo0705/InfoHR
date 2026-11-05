"""Run the accuracy set through the provider for each role and print the score. Writes nothing to the database.

Every case goes through provider.plan with the inputs services.answer builds. An entry case passes when the plan picks
the entry the role should get. A table case passes when the plan's parts settle (tables.settle, as the service does)
to the expected filters. Each role's entry cases and gated table cases are gated separately at 90%; ungated cases are
reported only. The users the rights come from are created inside a transaction that is rolled back at the end."""

import dataclasses
import logging
import time
import uuid
from datetime import date
from typing import Any

from accounts import roles as account_roles
from accounts.models import User
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from assistant import learning
from assistant.entries import ENTRY_BY_KEY, HelpEntry
from assistant.evalcheck import TableResult, check_table
from assistant.evalset import CASES, ROLE_ENTRIES, ROLES, TABLE_CASES, EvalCase, TableCase, expected
from assistant.matching import narrow_entries
from assistant.plan import Plan
from assistant.providers import Provider, get_provider
from assistant.services import PLAN_ENTRIES, QUESTION_LIMIT, phrases_for
from assistant.tables import can_open_table
from assistant.words import FilterWords, offered_words

logger = logging.getLogger(__name__)

OFF_MESSAGE = "Туслах идэвхгүй: .env-д ASSISTANT_* тохиргоо алга."
BELOW_MARK_MESSAGE = "Pass mark not reached: every role needs at least 90%."

# The group each role's rights come from (test_reach builds the same users). A role without a group has no rights.
_GROUP_OF: dict[str, str | None] = {
    "hr": account_roles.HR,
    "hr_off": account_roles.HR,
    "accountant": account_roles.ACCOUNTANT,
    "staff": account_roles.EMPLOYEE,
    "staff_off": account_roles.EMPLOYEE,
    "approver": account_roles.EMPLOYEE,
    "admin": account_roles.ADMIN,
    "auditor": account_roles.AUDITOR,
    "none": None,
}


def _role_user(role: str) -> User:
    """A login that holds the role's group. Created inside the run's transaction, which is rolled back."""
    user = User.objects.create_user(f"eval_{role}_{uuid.uuid4().hex[:8]}")
    # Every new user gets the Employee group (accounts/signals.py), so the groups are set, not added to: the role
    # «none» ends with no group at all, as the real no-group user does.
    group = _GROUP_OF[role]
    user.groups.set([Group.objects.get(name=group)] if group is not None else [])
    if role == "admin":
        user.is_staff = True
        user.save(update_fields=["is_staff"])
    return user


def _plan(
    provider: Provider,
    question: str,
    entries: list[HelpEntry],
    words: list[FilterWords],
    today: date,
    refusals: tuple[str, ...],
    pause: float,
    table_examples: tuple[tuple[str, str], ...] = (),
) -> Plan | None:
    """The provider's plan for the question, called as services.answer calls it: the question cut as the service cuts
    it, and the entries narrowed to the plan's share. None when the call fails (one bad call is one failed case)."""
    text = question.strip()[:QUESTION_LIMIT]
    if pause > 0:  # spaces the calls out for providers with a requests-per-minute limit
        time.sleep(pause)
    try:
        narrowed = narrow_entries(text, entries, limit=PLAN_ENTRIES)
        return provider.plan(
            text, narrowed, words, phrases_for(words, text), today, "", refusals, table_examples=table_examples
        )
    except Exception:
        logger.exception("The assistant eval could not get a plan for one case.")
        return None


def _entry_got(plan: Plan | None, role_keys: set[str]) -> str:
    """The entry the service would keep: an entry tool with a key the role may use; anything else counts as ""."""
    if plan is None:
        return "error"
    return plan.entry if plan.tool == "entry" and plan.entry in role_keys else ""


def _pct_ok(passed: int, total: int) -> bool:
    return passed * 10 >= total * 9  # the pass mark is 90%


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


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
        # Local filter sentences are scored as table cases, never gated (the spec's accuracy ruling).
        local_table_rows = [] if shipped_only else learning.local_table_tests()
        local_table_cases = [TableCase(t.question, t.expected, gated=False) for t in local_table_rows]
        # Read once per run, as services.answer reads them once per question.
        learned: dict[str, tuple[str, ...]] = {} if shipped_only else learning.learned_by_entry()
        refusals: tuple[str, ...] = () if shipped_only else learning.no_entry_questions()
        table_examples: tuple[tuple[str, str], ...] = () if shipped_only else learning.table_examples()

        header = f"Cases: shipped {len(CASES)}, local {len(tests)}"
        if tests:
            stamp = timezone.localtime(max(t.created_at for t in tests)).isoformat(timespec="seconds")
            header += f", newest {stamp}"
        self.stdout.write(header)
        gated_table = sum(c.gated for c in TABLE_CASES)
        self.stdout.write(
            f"Kinds: entry {len(cases)}, table {len(TABLE_CASES)} "
            f"({gated_table} gated, {len(TABLE_CASES) - gated_table} ungated), local table {len(local_table_cases)}"
        )

        today = timezone.localdate()
        roles = (options["role"],) if options["role"] else ROLES
        below_mark = False
        gated_passed = gated_total = 0
        with transaction.atomic():
            for role in roles:
                below, passed, total = self._run_role(
                    provider, role, cases, learned, refusals, table_examples, local_table_cases, today, options["pause"]
                )
                below_mark = below_mark or below
                gated_passed += passed
                gated_total += total
            transaction.set_rollback(True)  # nothing the eval made is kept
        self.stdout.write(f"Overall: {gated_passed}/{gated_total} gated cases")
        if below_mark:
            raise CommandError(BELOW_MARK_MESSAGE)

    def _run_role(
        self,
        provider: Provider,
        role: str,
        cases: list[EvalCase],
        learned: dict[str, tuple[str, ...]],
        refusals: tuple[str, ...],
        table_examples: tuple[tuple[str, str], ...],
        local_table_cases: list[TableCase],
        today: date,
        pause: float,
    ) -> tuple[bool, int, int]:
        """Scores one role. Returns (below the mark, gated cases passed, gated cases)."""
        user = _role_user(role)
        table_on = can_open_table(user)
        words = offered_words(user) if table_on else []  # no words for a user who may not open the table
        entries = [dataclasses.replace(ENTRY_BY_KEY[k], learned=learned.get(k, ())) for k in ROLE_ENTRIES[role]]
        role_keys = set(ROLE_ENTRIES[role])

        entry_passed = 0
        for case in cases:
            want = expected(case, role)
            plan = _plan(provider, case.question, entries, words, today, refusals, pause, table_examples)
            got = _entry_got(plan, role_keys)
            ok = got == want
            entry_passed += ok
            self.stdout.write(f"{_status(ok)} {role} | {case.question} | expected {want or '-'} | got {got or '-'}")
        below = not _pct_ok(entry_passed, len(cases))
        gated_passed, gated_total = entry_passed, len(cases)
        summary = f"{role}: {entry_passed}/{len(cases)} entries"

        if not table_on:
            self.stdout.write(f"{summary}; tables n/a (no staff table right)")
            return below, gated_passed, gated_total

        table_gated = [0, 0]  # passed, total
        table_ungated = [0, 0]
        table_local = [0, 0]
        for kind, tcases in (("table", TABLE_CASES), ("local table", local_table_cases)):
            for tcase in tcases:
                if tcase.roles and role not in tcase.roles:
                    continue
                plan = _plan(provider, tcase.question, entries, words, today, refusals, pause, table_examples)
                result = check_table(user, tcase, plan, today) if plan is not None else TableResult(False, "error")
                if kind == "local table":
                    bucket = table_local
                else:
                    bucket = table_gated if tcase.gated else table_ungated
                bucket[0] += result.passed
                bucket[1] += 1
                self._write_table(role, tcase, result, kind)
        below = below or not _pct_ok(table_gated[0], table_gated[1])
        gated_passed += table_gated[0]
        gated_total += table_gated[1]
        tables = f"tables {table_gated[0]}/{table_gated[1]} gated"
        if table_ungated[1]:
            tables += f", {table_ungated[0]}/{table_ungated[1]} ungated"
        if table_local[1]:
            tables += f", local {table_local[0]}/{table_local[1]} (not gated)"
        self.stdout.write(f"{summary}; {tables}")
        return below, gated_passed, gated_total

    def _write_table(self, role: str, case: TableCase, result: TableResult, kind: str) -> None:
        want = f"ask {case.ask}" if case.ask else (case.expected or "-")
        note = "" if case.gated else " (not gated)"
        self.stdout.write(
            f"{_status(result.passed)} {kind} {role} | {case.question} | expected {want} | got {result.got}{note}"
        )
