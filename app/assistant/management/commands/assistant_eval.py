"""Run the accuracy set through the provider for each role and print the score. Writes nothing to the database.

With --sql, runs the SQL accuracy set (assistant/sqleval.py) instead: each question is answered by the governed SQL path
as the role's user, against the Firebird database. It calls the provider, so it refuses to run without --yes-spend.

Every case goes through provider.plan with the inputs services.answer builds. An entry case passes when the plan picks
the entry the role should get. A table case passes when the plan's parts settle (tables.settle, as the service does)
to the expected filters. Each role's entry cases and gated table cases are gated separately at 90%; ungated cases are
reported only. The users the rights come from are created inside a transaction that is rolled back at the end."""

import dataclasses
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from accounts.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from leave.models import LeaveSettings

from assistant import learning
from assistant.columns import plan_extras
from assistant.entries import HelpEntry, allowed_entries
from assistant.evalcheck import ActionResult, TableResult, check_action, check_table
from assistant.evalset import ACTION_CASES, CASES, ROLES, TABLE_CASES, EvalCase, TableCase, expected
from assistant.fields import AskableField, hints_for
from assistant.matching import narrow_entries
from assistant.plan import Plan
from assistant.providers import Provider, get_provider
from assistant.role_users import make_role_user
from assistant.services import FIELD_HINTS, PLAN_ENTRIES, QUESTION_LIMIT, phrases_for
from assistant.sqleval import SQL_CASES, SQL_ROLES, check_sql_case
from assistant.tables import can_open_table
from assistant.words import FilterWords, offered_words

logger = logging.getLogger(__name__)

OFF_MESSAGE = "Туслах идэвхгүй: .env-д ASSISTANT_* тохиргоо алга."
BELOW_MARK_MESSAGE = "Pass mark not reached: every role needs at least 90%."
SPEND_MESSAGE = "The --sql run calls the provider and spends credit. Add --yes-spend to run it; nothing was run."

# The user kind each role is built from (assistant.role_users). The roles ending in «_off» are the same users with
# leave approval switched off.
_KIND_OF: dict[str, str] = {role: role.removesuffix("_off") for role in ROLES}


def _role_user(role: str) -> User:
    """A real user of the role, with the rights and records the role really has. Created inside the run's transaction,
    which is rolled back."""
    actor = User.objects.create_user(f"eval_actor_{uuid.uuid4().hex[:8]}")
    return make_role_user(actor, _KIND_OF[role], f"eval_{role}_{uuid.uuid4().hex[:8]}")


def _plan(
    provider: Provider,
    question: str,
    entries: list[HelpEntry],
    words: list[FilterWords],
    today: date,
    refusals: tuple[str, ...],
    pause: float,
    table_examples: tuple[tuple[str, str], ...] = (),
    previous: str = "",
    field_hints: Sequence[AskableField] = (),
    extras: Mapping[str, Any] | None = None,
) -> Plan | None:
    """The provider's plan for the question, called as services.answer calls it: the question cut as the service cuts
    it, and the entries narrowed to the plan's share. `previous` is the earlier answer's query of a follow-up case.
    `field_hints` are the registry fields the service would pass (only the action cases pass them). `extras` are the
    provider's extra plan inputs for this user (plan_extras: the rule columns of a provider that builds rules).
    None when the call fails (one bad call is one failed case)."""
    text = question.strip()[:QUESTION_LIMIT]
    if pause > 0:  # spaces the calls out for providers with a requests-per-minute limit
        time.sleep(pause)
    try:
        narrowed = narrow_entries(text, entries, limit=PLAN_ENTRIES)
        return provider.plan(
            text,
            narrowed,
            words,
            phrases_for(words, text),
            today,
            previous,
            refusals,
            table_examples=table_examples,
            field_hints=field_hints,
            **(extras or {}),
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
        parser.add_argument("--sql", action="store_true", help="Score the SQL accuracy set instead (needs Firebird).")
        parser.add_argument("--yes-spend", action="store_true", help="Allow the provider calls of --sql.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["sql"]:
            self._run_sql(options)
            return
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
            self._run_actions(provider, today, options["pause"], refusals, table_examples)
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
        # The roles ending in «_off» are the same users with leave approval switched off (inside the rolled-back run).
        LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": not role.endswith("_off")})
        table_on = can_open_table(user)
        words = offered_words(user) if table_on else []  # no words for a user who may not open the table
        extras = plan_extras(provider, user)  # the rule columns the service passes to a provider that builds rules
        # The entries the user is really offered (what services.answer passes), not a list kept by hand.
        entries = [dataclasses.replace(e, learned=learned.get(e.key, ())) for e in allowed_entries(user, today)]
        role_keys = {e.key for e in entries}

        entry_passed = 0
        for case in cases:
            want = expected(case, role, role_keys)
            plan = _plan(provider, case.question, entries, words, today, refusals, pause, table_examples, extras=extras)
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
                plan = _plan(
                    provider,
                    tcase.question,
                    entries,
                    words,
                    today,
                    refusals,
                    pause,
                    table_examples,
                    tcase.previous,
                    extras=extras,
                )
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

    def _run_sql(self, options: dict[str, Any]) -> None:
        """Scores the SQL accuracy set per role. Each role's cases are gated at 90%, like the entry cases."""
        if not options["yes_spend"]:
            raise CommandError(SPEND_MESSAGE)
        provider = get_provider()
        if provider is None:
            raise CommandError(OFF_MESSAGE)
        roles = (options["role"],) if options["role"] else SQL_ROLES
        below_mark = False
        total_passed = total = 0
        with transaction.atomic():
            for role in roles:
                user = _role_user(role)
                passed = count = 0
                for case in (c for c in SQL_CASES if c.role == role):
                    result = check_sql_case(case, user, provider)
                    passed += result.passed
                    count += 1
                    self.stdout.write(f"{_status(result.passed)} sql {role} | {case.question} | {result.reason}")
                below_mark = below_mark or not _pct_ok(passed, count)
                total_passed += passed
                total += count
                self.stdout.write(f"{role}: {passed}/{count} sql cases")
            transaction.set_rollback(True)  # nothing the eval made is kept
        self.stdout.write(f"Overall: {total_passed}/{total} sql cases")
        if below_mark:
            raise CommandError(BELOW_MARK_MESSAGE)

    def _run_actions(
        self,
        provider: Provider,
        today: date,
        pause: float,
        refusals: tuple[str, ...],
        table_examples: tuple[tuple[str, str], ...],
    ) -> None:
        """Scores the field and leave-form sentences once, as the hr role (they name a person and a field, not a help
        entry). Ungated: each case is reported and the count is printed, but none counts in the 90% gate."""
        user = _role_user("hr")
        LeaveSettings.objects.update_or_create(pk=1, defaults={"approval1_manager": True})
        entries = allowed_entries(user, today)
        words = offered_words(user)
        extras = plan_extras(provider, user)
        passed = 0
        for case in ACTION_CASES:
            plan = _plan(
                provider,
                case.question,
                entries,
                words,
                today,
                refusals,
                pause,
                table_examples,
                field_hints=hints_for(case.question, limit=FIELD_HINTS),
                extras=extras,
            )
            result = check_action(case, plan) if plan is not None else ActionResult(passed=False, got="error")
            passed += result.passed
            want = f"{case.tool} {case.field}".strip()
            self.stdout.write(
                f"{_status(result.passed)} action | {case.question} | expected {want} | got {result.got} (not gated)"
            )
        self.stdout.write(f"actions {passed}/{len(ACTION_CASES)} (not gated)")

    def _write_table(self, role: str, case: TableCase, result: TableResult, kind: str) -> None:
        want = f"ask {case.ask}" if case.ask else (case.expected or "-")
        note = "" if case.gated else " (not gated)"
        self.stdout.write(
            f"{_status(result.passed)} {kind} {role} | {case.question} | expected {want} | got {result.got}{note}"
        )
