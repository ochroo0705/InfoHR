"""Every model registered in the admin console must have a sidebar link (UNFOLD["SIDEBAR"] in config/settings.py).

The sidebar is a hand-written list, so a new `@admin.register` model is invisible until someone adds it there.
If a model is reached another way on purpose, add it to NOT_IN_SIDEBAR with the reason."""

from typing import Any

from django.conf import settings
from django.contrib import admin
from django.urls import reverse

# Registered on purpose without a sidebar link of their own (reached from a record page or a bespoke screen).
NOT_IN_SIDEBAR = {
    "employees_activityentry",
    "employees_jobrecord",
    "employees_salaryrecord",
    "leave_annualleaverule",
    "macs_employee",
    "recruitment_recruitmentsettings",  # TODO: confirm it has another way in; if not, it belongs in the sidebar
}


def _links(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        if node.get("link"):
            found.add(str(node["link"]))
        for value in node.values():
            _links(value, found)
    elif isinstance(node, list | tuple):
        for value in node:
            _links(value, found)


def test_every_admin_model_has_a_sidebar_link() -> None:
    links: set[str] = set()
    _links(settings.UNFOLD["SIDEBAR"], links)
    missing = sorted(
        key
        for key in (f"{m._meta.app_label}_{m._meta.model_name}" for m in admin.site._registry)
        if key not in NOT_IN_SIDEBAR and str(reverse(f"admin:{key}_changelist")) not in links
    )
    assert not missing, f"Add these to UNFOLD['SIDEBAR'] in config/settings.py (or to NOT_IN_SIDEBAR): {missing}"


def test_exempt_list_has_no_stale_names() -> None:
    registered = {f"{m._meta.app_label}_{m._meta.model_name}" for m in admin.site._registry}
    assert NOT_IN_SIDEBAR <= registered
