from typing import Any

from django import template
from employees.templatetags.hr import own_record
from leave.templatetags.leave_tags import requests_nav

from accounts.nav import NavGroup, top_nav

register = template.Library()


@register.simple_tag(takes_context=True)
def nav_groups(context: Any) -> list[NavGroup]:
    """The top bar's menu groups for the signed-in user (accounts/nav.py)."""
    return top_nav(context["request"], bool(own_record(context)), requests_nav(context))
