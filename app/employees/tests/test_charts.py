import pytest
from django.template import Context, Template

from employees.company_stats import Bar, Point
from employees.templatetags.charts import line_geometry

pytestmark = pytest.mark.django_db


def _coords(run: str) -> list[tuple[float, float]]:
    return [(float(a), float(b)) for a, b in (p.split(",") for p in run.split())]


def test_line_geometry_scales_to_the_box() -> None:
    (run,) = line_geometry([0, 10], width=200, height=60)
    (x0, y0), (x1, y1) = _coords(run)
    assert x0 == 0 and x1 == 200
    assert y0 == 60 and y1 == 0  # smallest value at the bottom, largest at the top


def test_line_geometry_breaks_on_none() -> None:
    runs = line_geometry([1, None, 3])
    assert len(runs) == 2


def test_line_geometry_all_equal_values_draws_a_flat_line_not_a_division_error() -> None:
    (run,) = line_geometry([5, 5, 5], width=200, height=60)
    ys = {y for _, y in _coords(run)}
    assert len(ys) == 1
    assert 0 <= ys.pop() <= 60


def test_line_geometry_empty_returns_no_runs() -> None:
    assert line_geometry([]) == []
    assert line_geometry([None, None]) == []


def test_line_chart_has_aria_label_with_first_and_last_value() -> None:
    points = [Point("2026-09", 214), Point("2026-10", 230), Point("2026-11", 240)]
    html = Template("{% load charts %}{% line_chart points '' 'Ажилтны тоо' %}").render(Context({"points": points}))
    assert 'role="img"' in html
    assert 'aria-label="Ажилтны тоо: 214 → 240"' in html


def test_line_chart_empty_shows_no_data_line() -> None:
    html = Template("{% load charts %}{% line_chart points '%' 'Эргэлт' %}").render(Context({"points": []}))
    assert "Мэдээлэл алга" in html
    assert "<svg" not in html


def test_bar_chart_prints_label_value_and_pct_width() -> None:
    bars = [Bar("Нягтлан", 4, 40), Bar("Бусад", 10, 100)]
    html = Template("{% load charts %}{% bar_chart bars 'Хэлтэс' %}").render(Context({"bars": bars}))
    assert "Нягтлан" in html
    assert ">4<" in html
    assert 'style="width: 40%"' in html
    assert 'role="img"' in html


def test_bar_chart_empty_shows_no_data_line() -> None:
    html = Template("{% load charts %}{% bar_chart bars 'Хэлтэс' %}").render(Context({"bars": []}))
    assert "Мэдээлэл алга" in html


def test_bar_chart_aria_label_lists_every_bar_and_is_escaped() -> None:
    bars = [Bar("Нягтлан", 4, 40), Bar('A"<b>', 10, 100)]
    html = Template("{% load charts %}{% bar_chart bars 'Хэлтэс' %}").render(Context({"bars": bars}))
    assert 'aria-label="Хэлтэс: Нягтлан 4, A&quot;&lt;b&gt; 10"' in html
    assert "<b>" not in html
