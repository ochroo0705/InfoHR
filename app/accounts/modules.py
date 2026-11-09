"""Optional modules: parts of MACS Human Capital an admin can switch off for an organisation that does not need them.

A module is declared once here (its key, texts, rights and addresses). Switching it off
 * hides it everywhere that asks a right: `User.has_perm` answers False for the module's rights (menu, command palette,
   help assistant, forms),
 * refuses its pages: `ModuleGateMiddleware` answers 404 for the module's addresses,
 * is read by the few places that do not ask a right (`enabled`).
The data of a module is never deleted: switching it on again brings everything back.

The state is one JSON text on `CompanySettings.modules`, {key: true|false}. A module not named there is on, so an
install that never opens the page keeps every module. The state is cached for CACHE_SECONDS (a few seconds late on
another worker is fine); `set_state` and `clear_cache` drop it at once.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from django.http import Http404, HttpRequest, HttpResponse

CACHE_SECONDS = 30
_cache: tuple[float, dict[str, bool]] | None = (
    None  # (expires at, state) kept per process, whatever the Django cache is
)


@dataclass(frozen=True)
class Module:
    key: str  # short lowercase word, the key stored in CompanySettings.modules
    label: str  # the name on the page
    description: str  # one sentence: what the module is for
    effects: tuple[str, ...]  # what disappears when it is off, one line each (shown on the page)
    perms: tuple[str, ...] = ()  # permission codenames ("app.codename") that read False while it is off
    perm_prefixes: tuple[str, ...] = ()  # every permission starting with one of these reads False while it is off
    namespaces: tuple[str, ...] = ()  # URL namespaces that answer 404 while it is off
    view_names: tuple[str, ...] = ()  # single "namespace:name" addresses that answer 404 while it is off


MODULES: tuple[Module, ...] = (
    Module(
        key="slots",
        label="Орон тооны төлөвлөгөө",
        description="Албан тушаал, салбар, оны орон тоог төлөвлөж, ажилд авахад хянана.",
        effects=(
            "Тохиргооны цэсийн «Орон тооны төлөвлөгөө» болон хуудас",
            "Ажилд авах, дахин авахад орон тоо шалгах, орон тоо давах зөвшөөрөл",
            "Сул орон тооны мөр (ажлын байрны зарын маягт)",
            "«Инженер, техникийн ажилтны судалгаа» тайлан",
        ),
        perms=("employees.manage_position_slots", "employees.override_position_slots"),
        view_names=("employees:slots", "employees:slot_add", "employees:slot_edit", "employees:slot_delete"),
    ),
    Module(
        key="recruitment",
        label="Ажилд авах",
        description="Сул орон тоо, ажил хүсэгч, ярилцлага, ажилд авах шат дамжлага.",
        effects=(
            "Дээд цэсний «Ажилд авах» болон бүх хуудас",
            "Ажил хүсэгчийг ажилтан болгох холбоос",
            "Туслах, хайлтын цэс дэх ажилд авах заавар",
        ),
        perm_prefixes=("recruitment.",),
        namespaces=("recruitment",),
    ),
)
BY_KEY: dict[str, Module] = {m.key: m for m in MODULES}


def _stored() -> dict[str, bool]:
    """The explicit choices from CompanySettings.modules; a bad or missing text reads as no choice."""
    from employees.models import CompanySettings  # local import: employees imports accounts

    text = CompanySettings.objects.filter(pk=1).values_list("modules", flat=True).first() or ""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in BY_KEY and isinstance(v, bool)}


def state() -> dict[str, bool]:
    """Every module's on/off, cached."""
    global _cache
    held = _cache
    if held is not None and held[0] > time.monotonic():
        return held[1]
    stored = _stored()
    fresh = {m.key: stored.get(m.key, True) for m in MODULES}
    _cache = (time.monotonic() + CACHE_SECONDS, fresh)
    return fresh


def enabled(key: str) -> bool:
    """Whether the module is on. An unknown key is on (a module that is not declared here cannot be switched off)."""
    return state().get(key, True)


def clear_cache() -> None:
    global _cache
    _cache = None


def set_state(changes: dict[str, bool]) -> None:
    """Store the on/off of the named modules (others keep their choice). Unknown keys are ignored."""
    from employees.models import CompanySettings

    row = CompanySettings.get()
    try:
        data = json.loads(row.modules or "{}")
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key, value in changes.items():
        if key in BY_KEY:
            data[key] = bool(value)
    row.modules = json.dumps(data, sort_keys=True)
    row.save(update_fields=["modules"])
    clear_cache()


def blocked_perm(perm: str) -> bool:
    """Whether this permission belongs to a module that is switched off. A right no module owns is answered without
    reading the state (most rights, so most `has_perm` calls cost nothing)."""
    owners = [m for m in MODULES if perm in m.perms or any(perm.startswith(p) for p in m.perm_prefixes)]
    if not owners:
        return False
    current = state()
    return any(not current[m.key] for m in owners)


def module_of_view(view_name: str, namespace: str) -> Module | None:
    """The module an address belongs to, if any."""
    for module in MODULES:
        if view_name in module.view_names or namespace in module.namespaces:
            return module
    return None


class ModuleGateMiddleware:
    """A page of a module that is switched off does not exist: 404 (the menu no longer links it, this stops a typed or
    saved address)."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self, request: HttpRequest, view_func: Callable[..., HttpResponse], args: tuple, kwargs: dict
    ) -> None:
        match = request.resolver_match
        if match is None:
            return None
        module = module_of_view(match.view_name, match.namespace)
        if module is not None and not enabled(module.key):
            raise Http404("module off")
        return None
