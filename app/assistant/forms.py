import re
from typing import Any

from django import forms
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.widgets import UnfoldAdminTextInputWidget

from assistant import learning
from assistant.catalog import MODELS
from assistant.entries import ENTRIES, ENTRY_BY_KEY
from assistant.models import AssistantSettings, HelpExample, HelpQuestion

ENTRY_CHOICES: list[tuple[str, str]] = [("", "Аль ч хариулт тохирохгүй")] + [
    (entry.key, entry.title) for entry in ENTRIES
]


class HelpExampleForm(forms.ModelForm):  # type: ignore[type-arg]
    """A correction: the question and the entry that should answer it. Rules come from `learning.check`."""

    entry = forms.ChoiceField(label="Зөв хариулт", choices=ENTRY_CHOICES, required=False)
    source = forms.ModelChoiceField(queryset=HelpQuestion.objects.all(), required=False, widget=forms.HiddenInput)

    class Meta:
        model = HelpExample
        fields = ("question", "entry", "expected", "kind", "active", "source")
        help_texts = {
            "question": "Нэр, хувийн мэдээллийг арилгана уу (жишээ нь [ажилтан]).",
            "expected": (
                "Хүснэгтийн асуултад шүүлтүүр, жишээ нь department~Санхүү&emptype=5. "
                "Хоосон бол туслахын хариултын жишээ."
            ),
        }
        widgets = {"kind": forms.RadioSelect}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The prefilled add form from the log: the readonly fields read `form.instance`, so the log row goes there too.
        if not self.is_bound and self.instance.pk is None and self.initial.get("source"):
            self.instance.source = HelpQuestion.objects.filter(pk=self.initial["source"]).first()
            self.instance.question = self.initial.get("question", "")
        # An orphan (its entry key was removed from the code) keeps its key selectable, so saving the form does not
        # silently blank it. `learning.check` refuses it while active.
        orphan = self.instance.entry
        if self.instance.pk and orphan and orphan not in ENTRY_BY_KEY:
            field = self.fields["entry"]
            if isinstance(field, forms.ChoiceField):
                field.choices = [*ENTRY_CHOICES, (orphan, "Энэ хариулт байхгүй болсон")]

    def clean(self) -> dict[str, Any]:
        cleaned: dict[str, Any] = super().clean() or {}
        question = cleaned.get("question")
        entry = cleaned.get("entry")
        kind = cleaned.get("kind")
        if question is None or entry is None or kind is None or "expected" not in cleaned:
            return cleaned  # a field already failed; its own message is shown
        expected = cleaned["expected"] or ""
        checks = learning.check(
            question, entry, kind, cleaned.get("active", False), exclude_pk=self.instance.pk, expected=expected
        )
        for message in checks:
            self.add_error(None, message)
        return cleaned


MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,59}$")


class ModelInput(UnfoldAdminTextInputWidget):  # type: ignore[misc]
    """A text box for the model id with the known models of each provider as suggestions (one datalist per
    provider; the settings page script points the box at the chosen provider's list). Any id may be typed."""

    def render(self, name: str, value: Any, attrs: dict[str, Any] | None = None, renderer: Any = None) -> str:
        attrs = {**(attrs or {}), "list": "assistant-models-claude"}
        html = str(super().render(name, value, attrs, renderer))
        lists = "".join(
            format_html(
                '<datalist id="assistant-models-{}">{}</datalist>',
                provider,
                format_html_join("", '<option value="{}">{}</option>', models),
            )
            for provider, models in MODELS.items()
        )
        return mark_safe(html + lists)  # noqa: S308 built from format_html parts above


class AssistantSettingsForm(forms.ModelForm):  # type: ignore[type-arg]
    """Provider, key, model and timeout. The key box is write-only: leaving it empty keeps the saved key."""

    api_key = forms.CharField(
        label="API түлхүүр",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    model = forms.CharField(
        label="Загвар", required=False, max_length=60, widget=ModelInput(attrs={"autocomplete": "off"})
    )

    class Meta:
        model = AssistantSettings
        fields = ("provider", "api_key", "model", "timeout")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["api_key"].help_text = (
            "Түлхүүр хадгалагдсан. Солих бол шинийг бичнэ үү, хэвээр үлдээх бол хоосон орхино уу."
            if self.instance.api_key
            else "Түлхүүр хадгалагдаагүй."
        )
        self.fields["provider"].help_text = "Хоосон бол туслах унтарна."
        self.fields["model"].help_text = "Жагсаалтаас сонгоно уу, эсвэл өөр загварын нэрийг гараар бичнэ үү."

    def clean_api_key(self) -> str:
        return str(self.cleaned_data.get("api_key") or "").strip() or self.instance.api_key

    def clean(self) -> dict[str, Any]:
        data = super().clean() or {}
        provider, model = data.get("provider", ""), str(data.get("model", "")).strip()
        data["model"] = model
        if provider:
            if not model:
                self.add_error("model", "Загвараа сонгох эсвэл бичнэ үү.")
            elif not MODEL_PATTERN.match(model):
                self.add_error("model", "Загварын нэр буруу байна (латин үсэг, тоо, . _ : / - л болно).")
            if not data.get("api_key") and "api_key" not in self.errors:
                self.add_error("api_key", "API түлхүүр оруулна уу.")
        return data
