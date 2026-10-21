import pytest
from django import forms

from employees.forms import StyledForm
from employees.templatetags.hr import field

pytestmark = pytest.mark.django_db


class _NotesForm(StyledForm):
    text = forms.CharField(widget=forms.Textarea(attrs={"rows": "10"}))


def test_inline_textarea_starts_at_one_line_and_grows() -> None:
    html = str(field(_NotesForm()["text"])["widget"])
    assert 'rows="1"' in html and "[field-sizing:content]" in html and "resize-none" in html


def test_form_textareas_do_not_default_to_ten_rows() -> None:
    html = str(_NotesForm()["text"])
    assert 'rows="2"' in html and 'rows="10"' not in html


def test_field_tag_form_id() -> None:
    from django.template import Context, Template

    form = _NotesForm()
    default = Template('{% load hr %}{% field form.text "w-full" %}').render(Context({"form": form}))
    section = Template('{% load hr %}{% field form.text "w-full" "sec-identity" %}').render(Context({"form": form}))
    assert 'form="emp-form"' in default
    assert 'form="sec-identity"' in section and 'form="emp-form"' not in section


def test_field_tag_boxed_has_border() -> None:
    from django.template import Context, Template

    form = _NotesForm()
    plain = Template('{% load hr %}{% field form.text "w-full" %}').render(Context({"form": form}))
    boxed = Template('{% load hr %}{% field form.text "w-full" "sec-identity" boxed=True %}').render(
        Context({"form": form})
    )
    assert "rounded-lg border border-slate-300 px-3 py-2 text-sm" not in plain  # edit-in-place stays borderless
    assert "rounded-lg border border-slate-300 px-3 py-2 text-sm" in boxed and "w-full" in boxed
