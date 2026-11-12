import json
from collections.abc import Sequence
from typing import Any

import sqlglot
from django.conf import settings
from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed, HttpResponseRedirect, JsonResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from sqlcore.firebird import Firebird
from sqlglot import exp
from unfold.admin import ModelAdmin

from . import learning
from .catalog import PROVIDER_CHOICES
from .check import check_connection
from .entries import ENTRY_BY_KEY
from .forms import AssistantSettingsForm, HelpExampleForm
from .models import AssistantSettings, HelpExample, HelpQuestion, SavedTable, VerifiedQuery, VerifiedStatus


@admin.register(HelpQuestion)
class HelpQuestionAdmin(ModelAdmin):  # type: ignore[misc]
    """The question log is read-only: rows are written by the assistant service only."""

    list_display = (
        "asked_at",
        "user",
        "question",
        "outcome",
        "error",
        "entry",
        "tool",
        "not_applied_short",
        "corrected",
        "duration_ms",
        "tokens_in",
        "tokens_out",
        "sql_rows",
        "salary_flag",
    )
    list_filter = ("outcome", "tool", "entry", "asked_at", "user")
    search_fields = ("question", "query")
    list_select_related = ("user",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_queryset(self, request: HttpRequest) -> QuerySet[HelpQuestion]:
        """Annotates whether an active correction uses the row as its source (one query for the whole page)."""
        queryset: QuerySet[HelpQuestion] = super().get_queryset(request)
        return queryset.annotate(corrected=Exists(HelpExample.objects.filter(source=OuterRef("pk"), active=True)))

    @admin.display(boolean=True, description="Засварласан")
    def corrected(self, obj: HelpQuestion) -> bool:
        return bool(getattr(obj, "corrected", False))  # set by get_queryset

    @admin.display(description="Хэрэглээгүй хэсэг")
    def not_applied_short(self, obj: HelpQuestion) -> str:
        """The parts the answer could not use, cut to 60 characters in the list; the full text is in the row."""
        return obj.not_applied if len(obj.not_applied) <= 60 else obj.not_applied[:60] + "…"

    def get_list_display(self, request: HttpRequest) -> Sequence[Any]:
        """Adds the name warning after the question, and the «Засах» link when the user may add corrections.
        The employee names are loaded once per changelist request, not once per row."""
        names = learning.employee_names()

        @admin.display(description="Анхааруулга")
        def name_flag(obj: HelpQuestion) -> str:
            return "⚠ Нэр" if learning.name_hits(obj.question, names) else ""

        columns = list(super().get_list_display(request))
        columns.insert(columns.index("question") + 1, name_flag)
        if request.user.has_perm("assistant.add_helpexample"):

            @admin.display(description="Засвар")
            def fix_link(obj: HelpQuestion) -> str:
                url = reverse("admin:assistant_helpexample_add") + f"?source={obj.pk}"
                return format_html('<a href="{}">Засах</a>', url)

            columns.append(fix_link)
        return columns


def _name_message(hits: list[str]) -> str:
    """The warning about employee names in a question, shown on the change page and after a save."""
    return "⚠ Нэр байж магадгүй: " + ", ".join(f"«{hit}»" for hit in hits)


@admin.register(HelpExample)
class HelpExampleAdmin(ModelAdmin):  # type: ignore[misc]
    """Corrections: what a question should be answered with. Rows are never deleted; switch `active` off instead."""

    form = HelpExampleForm
    list_display = (
        "question",
        "entry_title",
        "kind",
        "active",
        "created_by",
        "created_at",
        "source_link",
    )
    list_filter = ("kind", "active", "entry")
    search_fields = ("question",)
    list_select_related = ("created_by", "source")
    actions = ("activate", "deactivate", "export_json")
    # `source` itself is the hidden form field (see HelpExampleForm); the readable link is `source_link`.
    readonly_fields = (
        "name_warning",
        "asker_entries",
        "source_link",
        "created_by",
        "created_at",
        "changed_at",
    )

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_list_display(self, request: HttpRequest) -> Sequence[Any]:
        """Adds the usage column before `created_by`. Its used-ids set is computed once per changelist request."""
        used = learning.used_example_ids()

        @admin.display(description="Хэрэглээ")
        def usage(obj: HelpExample) -> str:
            return learning.usage_label(obj, used)

        columns = list(super().get_list_display(request))
        columns.insert(columns.index("created_by"), usage)
        return columns

    @admin.display(description="Зөв хариулт")
    def entry_title(self, obj: HelpExample) -> str:
        if obj.expected:  # a filter sentence: the filter query it should give, cut for the list
            return "Шүүлтүүр: " + (obj.expected if len(obj.expected) <= 60 else obj.expected[:60] + "…")
        if not obj.entry:
            return "Аль ч хариулт тохирохгүй"
        entry = ENTRY_BY_KEY.get(obj.entry)
        return entry.title if entry else "Энэ хариулт байхгүй болсон"

    @admin.display(description="Анхааруулга")
    def name_warning(self, obj: HelpExample) -> str:
        hits = learning.name_hits(obj.question)
        return _name_message(hits) if hits else "—"

    @admin.display(description="Асуусан хүн")
    def asker_entries(self, obj: HelpExample) -> str:
        source = obj.source
        if source is None:
            return "—"
        titles = [ENTRY_BY_KEY[key].title for key in source.allowed.split(",") if key in ENTRY_BY_KEY]
        if not titles:
            return "—"
        return "Асуусан хүнд боломжтой байсан: " + ", ".join(titles)

    @admin.display(description="Эх асуулт")
    def source_link(self, obj: HelpExample) -> str:
        if obj.source_id is None:
            return "—"
        url = reverse("admin:assistant_helpquestion_change", args=[obj.source_id])
        return format_html('<a href="{}">Асуулт #{}</a>', url, obj.source_id)

    def get_changeform_initial_data(self, request: HttpRequest) -> dict[str, Any]:
        """`?source=<pk>` from the log: prefill the question and entry the asker saw, as a new example."""
        raw = request.GET.get("source", "")
        source = HelpQuestion.objects.filter(pk=int(raw)).first() if raw.isdecimal() else None
        if source is None:
            return {}
        return {
            "question": source.question,
            "entry": source.entry,
            "kind": "example",
            "active": True,
            "source": source.pk,
        }

    @admin.action(description="Идэвхжүүлэх", permissions=["change"])
    def activate(self, request: HttpRequest, queryset: QuerySet[HelpExample]) -> None:
        """Switch on each inactive row that passes `learning.check`. Rows are checked one by one, so a row switched
        on here counts against the rows after it. Rows that are already active are left out of the message."""
        done = 0
        skipped: list[str] = []
        for row in queryset.filter(active=False).order_by("created_at", "pk"):
            problems = learning.check(
                row.question, row.entry, row.kind, active=True, exclude_pk=row.pk, expected=row.expected
            )
            if problems:
                skipped.append(f"«{row.question}» ({problems[0]})")
                continue
            row.active = True
            row.save(update_fields=["active", "changed_at"])
            done += 1
        text = f"{done} идэвхжлээ, {len(skipped)} алгаслаа"
        if skipped:
            messages.warning(request, f"{text}: " + "; ".join(skipped))
        else:
            messages.success(request, text)

    @admin.action(description="Идэвхгүй болгох", permissions=["change"])
    def deactivate(self, request: HttpRequest, queryset: QuerySet[HelpExample]) -> None:
        """Rows are saved one by one, not with `update()`: the audit receivers only run on a save (spec §4).
        The count is the rows actually switched off (already inactive rows are not counted)."""
        count = 0
        with transaction.atomic():
            for row in queryset.filter(active=True):
                row.active = False
                row.save(update_fields=["active", "changed_at"])
                count += 1
        messages.success(request, f"{count} идэвхгүй болголоо")

    @admin.action(description="Экспортлох", permissions=["view"])
    def export_json(self, request: HttpRequest, queryset: QuerySet[HelpExample]) -> HttpResponse:
        """The active corrections as a JSON file for review (see `learning.export_payload`)."""
        body = json.dumps(learning.export_payload(queryset), ensure_ascii=False)
        response = HttpResponse(body, content_type="application/json; charset=utf-8")
        filename = f"assistant_export_{timezone.localdate():%Y-%m-%d}.json"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def save_model(self, request: HttpRequest, obj: HelpExample, form: Any, change: bool) -> None:
        if not change and request.user.is_authenticated:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        hits = learning.name_hits(obj.question)
        if hits:
            messages.warning(request, _name_message(hits))


# Column names that hold a person's name, and the ones that hold a person's or a record's number (EMP_ID, CHILD_ID ...).
_NAME_COLUMNS = frozenset({"FIRST_NAME", "LAST_NAME"})


def _names_a_person(sql: str) -> bool:
    """True when the SQL compares a name column with a string, or an ..ID column with a whole number, using = IN or
    LIKE (for a number, = and IN only). Such a literal points at one person, and an approved example is shown to other
    askers. Gender and status words and numeric thresholds such as AMOUNT > 1000000 are not refused."""
    root = sqlglot.parse_one(sql, dialect=Firebird)  # the checker has parsed it already: one SELECT
    for node in root.find_all(exp.EQ, exp.In, exp.Like):
        if isinstance(node, exp.In):
            pairs = [(node.this, value) for value in node.expressions]
        elif isinstance(node, exp.Like):
            pairs = [(node.this, node.expression)]
        else:
            pairs = [(node.this, node.expression), (node.expression, node.this)]
        for column, value in pairs:
            if not (isinstance(column, exp.Column) and isinstance(value, exp.Literal)):
                continue
            name = column.name.upper()
            if value.is_string and name in _NAME_COLUMNS:
                return True
            if value.is_number and not isinstance(node, exp.Like) and name.endswith("ID"):
                return True
    return False


def _approval_check(reviewer: Any, row: VerifiedQuery) -> tuple[str, str]:
    """Why a proposed query may not be approved (the reason, or "" when it may), and the views it uses now.

    The SQL is checked again against the PROPOSER's current catalogue, so a right lost since the proposal counts. The
    question must name no employee, the SQL must name no person (see `_names_a_person`), and the reviewer must not be
    the proposer."""
    from hr_sql.catalogue import catalogue_for  # lazy: the governed catalogue loads the HR descriptions
    from sqlcore.check import CheckError, check_sql

    # needs native read
    if row.proposed_by_id is not None and row.proposed_by_id == reviewer.pk:
        return "өөрийн саналыг өөрөө батлах боломжгүй", ""
    # needs native read
    if learning.name_hits(row.question):
        return "асуултад ажилтны нэр байна", ""
    if row.proposed_by is None:
        return "санал болгосон хүн байхгүй", ""  # needs native read
    try:
        checked = check_sql(row.sql, catalogue_for(row.proposed_by))
    except CheckError:
        return "SQL одоо шалгалтад тэнцэхгүй байна", ""  # needs native read
    # needs native read
    if _names_a_person(row.sql):
        return "SQL-д тодорхой ажилтны нэр эсвэл дугаар заасан байна", ""
    return "", ",".join(sorted(checked.views))[:200]


@admin.register(VerifiedQuery)
class VerifiedQueryAdmin(ModelAdmin):  # type: ignore[misc]
    """The review queue for answers marked correct. Rows are not edited by hand: approval and rejection are the actions,
    and approval re-checks the SQL (see `_approval_check`). The change page only shows the row."""

    list_display = ("created_at", "question", "status", "views", "proposed_by", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    search_fields = ("question",)
    list_select_related = ("proposed_by", "reviewed_by")
    actions = ("approve", "reject")
    readonly_fields = (
        "question",
        "sql",
        "views",
        "status",
        "source",
        "proposed_by",
        "reviewed_by",
        "reviewed_at",
        "note",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def save_model(self, request: HttpRequest, obj: VerifiedQuery, form: Any, change: bool) -> None:
        """Nothing to save: every field is read-only, so the change page cannot set a status by hand."""

    @admin.action(description="Зөвшөөрөх", permissions=["change"])  # needs native read
    def approve(self, request: HttpRequest, queryset: QuerySet[VerifiedQuery]) -> None:
        done = 0
        refused: list[str] = []
        for row in queryset.filter(status=VerifiedStatus.PROPOSED).select_related("proposed_by"):
            problem, views = _approval_check(request.user, row)
            if problem:
                refused.append(f"#{row.pk} ({problem})")
                continue
            row.status = VerifiedStatus.APPROVED
            row.views = views
            row.reviewed_by = request.user  # type: ignore[assignment]
            row.reviewed_at = timezone.now()
            row.save(update_fields=["status", "views", "reviewed_by", "reviewed_at"])
            done += 1
        text = f"{done} зөвшөөрлөө, {len(refused)} алгаслаа"  # needs native read
        if refused:
            messages.warning(request, f"{text}: " + "; ".join(refused))
        else:
            messages.success(request, text)

    @admin.action(description="Татгалзах", permissions=["change"])  # needs native read
    def reject(self, request: HttpRequest, queryset: QuerySet[VerifiedQuery]) -> None:
        count = 0
        with transaction.atomic():
            for row in queryset.filter(status=VerifiedStatus.PROPOSED):
                row.status = VerifiedStatus.REJECTED
                row.reviewed_by = request.user  # type: ignore[assignment]
                row.reviewed_at = timezone.now()
                row.save(update_fields=["status", "reviewed_by", "reviewed_at"])
                count += 1
        messages.success(request, f"{count} татгалзлаа")  # needs native read


@admin.register(SavedTable)
class SavedTableAdmin(ModelAdmin):  # type: ignore[misc]
    """Saved workspace tables, for review. Tables are saved from the workspace and listed under «Тайлан»; the admin
    only lists them and deletes with the usual permission."""

    list_display = ("name", "visibility", "author", "updated_at")
    list_filter = ("visibility",)
    search_fields = ("name",)
    list_select_related = ("author",)
    readonly_fields = ("name", "visibility", "sql", "labels", "settings", "author", "created_at", "updated_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False  # the SQL must only come from a checked workspace tab; a change here would skip that check


@admin.register(AssistantSettings)
class AssistantSettingsAdmin(ModelAdmin):  # type: ignore[misc]
    """One settings page, no list. Before the first save the page starts from the .env values (the key included, so
    saving keeps it); nothing is written until Save, so just opening the page never changes how the assistant runs."""

    form = AssistantSettingsForm
    change_form_after_template = "admin/assistant/test_connection.html"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_object(
        self, request: HttpRequest, object_id: str, from_field: str | None = None
    ) -> AssistantSettings | None:
        row = AssistantSettings.objects.filter(pk=1).first()
        if row is not None:
            return row
        return AssistantSettings(
            pk=1,
            provider=settings.ASSISTANT_PROVIDER if settings.ASSISTANT_PROVIDER in dict(PROVIDER_CHOICES) else "",
            api_key=settings.ASSISTANT_API_KEY,
            model=settings.ASSISTANT_MODEL,
            timeout=settings.ASSISTANT_TIMEOUT,
        )

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        return HttpResponseRedirect(reverse("admin:assistant_assistantsettings_change", args=[1]))

    def get_urls(self) -> list[Any]:
        custom = [
            path("test/", self.admin_site.admin_view(self.test_connection), name="assistant_assistantsettings_test"),
        ]
        return custom + list(super().get_urls())

    def test_connection(self, request: HttpRequest) -> HttpResponse:
        """Tries one tiny call with the values typed in the form (an empty key box means the saved key) and says
        whether it worked. Saves nothing."""
        if request.method != "POST":
            return HttpResponseNotAllowed(["POST"])
        if not self.has_change_permission(request):
            return JsonResponse({"ok": False, "message": "Эрх хүрэлцэхгүй."}, status=403)
        form = AssistantSettingsForm(request.POST, instance=self.get_object(request, "1"))
        if not form.is_valid():
            problems = "; ".join(
                f"{form.fields[name].label}: {' '.join(str(e) for e in errors)}"
                for name, errors in form.errors.items()
                if name in form.fields
            )
            return JsonResponse({"ok": False, "message": problems or "Талбаруудаа шалгана уу."})
        ok, message = check_connection(form.cleaned_data)
        return JsonResponse({"ok": ok, "message": message})
