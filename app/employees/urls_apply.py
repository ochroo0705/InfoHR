from django.urls import path, re_path

from . import views_apply

app_name = "apply"

urlpatterns = [
    path("<str:token>/", views_apply.apply_form, name="form"),
    path("<str:token>/draft/", views_apply.apply_draft, name="draft"),
    # Any other path under /apply/ (a token with a slash, for example) gets the same answer as an unknown token.
    re_path(r"^[\s\S]*$", views_apply.apply_not_found, name="not_found"),  # [\s\S] also matches a newline
]
