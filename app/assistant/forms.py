from typing import Any

from django import forms

from assistant import learning
from assistant.entries import ENTRIES, ENTRY_BY_KEY
from assistant.models import HelpExample, HelpQuestion

ENTRY_CHOICES: list[tuple[str, str]] = [("", "Аль ч хариулт тохирохгүй")] + [
    (entry.key, entry.title) for entry in ENTRIES
]


class HelpExampleForm(forms.ModelForm):  # type: ignore[type-arg]
    """A correction: the question and the entry that should answer it. Rules come from `learning.check`."""

    entry = forms.ChoiceField(label="Зөв хариулт", choices=ENTRY_CHOICES, required=False)
    source = forms.ModelChoiceField(queryset=HelpQuestion.objects.all(), required=False, widget=forms.HiddenInput)

    class Meta:
        model = HelpExample
        fields = ("question", "entry", "kind", "active", "source")
        help_texts = {
            "question": "Нэр, хувийн мэдээллийг арилгана уу (жишээ нь [ажилтан]).",
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
        if question is None or entry is None or kind is None:
            return cleaned  # a field already failed; its own message is shown
        for message in learning.check(question, entry, kind, cleaned.get("active", False), exclude_pk=self.instance.pk):
            self.add_error(None, message)
        return cleaned
