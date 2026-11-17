import inspect
import re
import sys
from collections import Counter
from functools import cache
from pathlib import Path
from types import ModuleType

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import URLPattern, URLResolver, get_resolver

SKIPPED_PREFIXES = ("admin/", "api/", "static")
TEMPLATE_RE = re.compile(r'"([\w/]+\.html)"')
POST_RE = re.compile(r"\bPOST\b|def post\(")
STEP_GROUPS = {
    "me": 2,
    "": 2,
    "employees": 3,
    "leave": 4,
    "checklists": 4,
    "recruitment": 4,
    "lists": 4,
    "logs": 4,
    "reports": 5,
    "assistant": 6,
    "apply": 6,
}
STEPS = range(1, 8)


def _step(path: str) -> int:
    first = path.split("/", 1)[0]
    return STEP_GROUPS.get(first, 7)


def _clean(text: str) -> str:
    return text.replace("^", "").replace("$", "").replace("|", r"\|")


def _walk(patterns: list, prefix: str = ""):  # type: ignore[no-untyped-def]
    for item in patterns:
        if isinstance(item, URLResolver):
            yield from _walk(item.url_patterns, prefix + str(item.pattern))
        elif isinstance(item, URLPattern):
            yield prefix + str(item.pattern), item


@cache
def _module_source(module: ModuleType | None) -> str:
    if module is None:
        return ""
    try:
        return inspect.getsource(module)
    except (OSError, TypeError):
        return ""


@cache
def _template_dirs() -> tuple[Path, ...]:
    dirs: list[Path] = []
    for engine in settings.TEMPLATES:
        dirs.extend(Path(str(d)) for d in engine.get("DIRS", []))
    for app in apps.get_app_configs():
        dirs.append(Path(app.path) / "templates")
    return tuple(dirs)


def _find_template(name: str) -> Path | None:
    for directory in _template_dirs():
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _view_of(callback: object) -> tuple[str, object]:
    view_class = getattr(callback, "view_class", None)
    if view_class is not None:
        target = view_class
    else:
        target = inspect.unwrap(callback)  # type: ignore[arg-type]
    module = getattr(target, "__module__", "")
    name = getattr(target, "__qualname__", repr(target))
    return f"{module}.{name}", sys.modules.get(module)


def _row_for(full: str, pattern: URLPattern) -> str:
    view_name, module = _view_of(pattern.callback)
    source = _module_source(module)
    methods = "GET+POST" if POST_RE.search(source) else ("GET" if source else "?")

    templates: list[str] = []
    for match in TEMPLATE_RE.finditer(source):
        if match.group(1) not in templates:
            templates.append(match.group(1))
    htmx = "-"
    if templates:
        htmx = "no"
        for template in templates:
            found = _find_template(template)
            if found is None:
                htmx = "?"
                continue
            if "hx-" in found.read_text(encoding="utf-8", errors="ignore"):
                htmx = "yes"
                break
    template_cell = ", ".join(templates) if templates else "-"
    route_name = pattern.name or ""
    step = _step(full)
    return f"| /{_clean(full)} | {route_name} | {view_name} | {methods} | {template_cell} | {htmx} | {step} |"


class Command(BaseCommand):
    help = "Write a Markdown table of every page route, with its view, template, htmx use and frontend step."

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument("out_path", help="Where to write the Markdown inventory.")

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        rows: list[str] = []
        counts: Counter[int] = Counter()
        for full, pattern in _walk(get_resolver().url_patterns):
            full = full.lstrip("^")
            if full.startswith(SKIPPED_PREFIXES):
                continue
            rows.append(_row_for(full, pattern))
            counts[_step(full)] += 1

        lines = [
            "# Frontend split route inventory",
            "",
            "| path | name | view (module.func) | methods | template(s) | htmx | step |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            *rows,
            "",
            "## Routes per step",
            "",
            "| step | routes |",
            "| --- | --- |",
            *[f"| {step} | {counts.get(step, 0)} |" for step in STEPS],
            f"| total | {len(rows)} |",
            "",
        ]
        out = Path(options["out_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        self.stdout.write(f"Wrote {len(rows)} routes to {out}")
