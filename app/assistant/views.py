"""The help assistant's ask view: one question in, one answer card out (htmx, posted from the Ctrl+K palette)."""

from accounts.models import User
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from assistant.providers import get_provider
from assistant.services import answer


@login_required
@require_POST
def ask(request: HttpRequest) -> HttpResponse:
    question = request.POST.get("q", "").strip()
    if not question:
        return HttpResponseBadRequest()
    provider = get_provider()
    if provider is None:
        raise Http404
    assert isinstance(request.user, User)
    result = answer(request.user, question, timezone.localdate(), provider)
    return render(request, "assistant/_answer.html", {"result": result})
