"""My page («Миний хуудас», spec 5.6): the logged-in user's own record, leave balance, own requests and, for an
approver, the requests waiting for them. Also the own-result notices (approved or rejected) and their dismissal.

Only the user's own record is shown here, so no view right is needed (spec 5.7). The rules, and the page's facts,
live in employees.services.me_page (me_facts); this module only renders them.
"""

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from employees import attention
from employees.access import own_employee
from employees.services.me_page import decided, me_facts


def _user(request: HttpRequest) -> User:
    assert isinstance(request.user, User)
    return request.user


@login_required
def me_page(request: HttpRequest) -> HttpResponse:
    user = _user(request)
    employee = own_employee(user)
    if employee is None:  # a login without an employee record has no My page
        raise Http404
    return render(request, "employees/me.html", me_facts(user, employee, timezone.localdate()))


@login_required
@require_POST
def dismiss_notice(request: HttpRequest) -> HttpResponse:
    """«Мэдлээ» on one result notice. Only a notice of the user's own request can be dismissed; the answer is empty,
    so htmx removes the notice from the page."""
    user = _user(request)
    employee = own_employee(user)
    if employee is None:
        raise Http404
    key = request.POST.get("key", "")
    found = next((n for n in decided(employee) if n.item.key == key), None)
    if found is None:
        raise Http404
    attention.dismiss(user, found.item)
    return HttpResponse("")
