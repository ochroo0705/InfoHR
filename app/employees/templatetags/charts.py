"""Inline SVG / CSS charts for the Today page strip: a line and a row of bars. No JavaScript, no chart library."""

from django import template

from employees.company_stats import Bar, Point

register = template.Library()

NO_DATA = "Мэдээлэл алга"


def _num(value: float) -> str:
    return f"{value:g}"


def _runs(values: list[float | None], width: int, height: int) -> list[list[tuple[float, float]]]:
    present = [v for v in values if v is not None]
    if not present:
        return []
    low, high = min(present), max(present)
    span = high - low
    step = width / max(len(values) - 1, 1)
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for i, v in enumerate(values):
        if v is None:
            if current:
                runs.append(current)
            current = []
            continue
        y = height / 2 if span == 0 else height - (v - low) * height / span  # flat when every value is equal
        current.append((round(i * step, 1), round(y, 1)))
    if current:
        runs.append(current)
    return runs


def line_geometry(values: list[float | None], width: int = 200, height: int = 60) -> list[str]:
    """One SVG `points` string per unbroken run of values; a None breaks the line."""
    return [" ".join(f"{_num(x)},{_num(y)}" for x, y in run) for run in _runs(values, width, height)]


@register.inclusion_tag("employees/_chart_line.html")
def line_chart(points: list[Point], unit: str, title: str) -> dict[str, object]:
    """A line over `points` (oldest first). `unit` is appended to the printed values («%» or «»)."""
    width, height = 200, 60
    values = [p.value for p in points]
    runs = _runs(values, width, height)
    present = [p for p in points if p.value is not None]
    label = title
    last_dot: tuple[float, float] | None = None
    if present:
        first, last = present[0], present[-1]
        assert first.value is not None and last.value is not None
        label = f"{title}: {_num(first.value)}{unit} → {_num(last.value)}{unit}"
        last_dot = runs[-1][-1]
    return {
        "points": points,
        "polylines": line_geometry(values, width, height),
        "last_dot": last_dot,
        "width": width,
        "height": height,
        "label": label,
        "title": title,
        "first_label": points[0].label if points else "",
        "last_label": points[-1].label if points else "",
        "last_text": f"{_num(present[-1].value)}{unit}" if present and present[-1].value is not None else "",
        "no_data": not present,
        "no_data_text": NO_DATA,
    }


@register.inclusion_tag("employees/_chart_bars.html")
def bar_chart(bars: list[Bar], title: str) -> dict[str, object]:
    """Horizontal bars: label, a track filled to `pct` percent, and the value."""
    summary = f"{title}: " + ", ".join(f"{b.label} {b.value}" for b in bars)  # role="img" hides the rows
    return {"bars": bars, "title": title, "summary": summary, "no_data": not bars, "no_data_text": NO_DATA}
