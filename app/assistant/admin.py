import json
from collections.abc import Sequence
from typing import Any

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from . import learning
from .entries import ENTRY_BY_KEY
from .forms import HelpExampleForm
from .models import HelpExample, HelpQuestion


@admin.register(HelpQuestion)
class HelpQuestionAdmin(ModelAdmin):  # type: ignore[misc]
    """The question log is read-only: rows are written by the assistant service only."""

    list_display = ("asked_at", "user", "question", "outcome", "entry", "corrected", "duration_ms")
    list_filter = ("outcome", "entry", "asked_at", "user")
    search_fields = ("question",)
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
            problems = learning.check(row.question, row.entry, row.kind, active=True, exclude_pk=row.pk)
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
