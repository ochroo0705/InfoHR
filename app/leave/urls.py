from django.urls import path

from . import views, views_requests

app_name = "leave"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("requests/", views_requests.requests_list, name="requests"),
    path("requests/<int:pk>/", views_requests.request_detail, name="request_detail"),
    path("requests/<int:pk>/approve/", views_requests.request_approve, name="request_approve"),
    path("requests/<int:pk>/reject/", views_requests.request_reject, name="request_reject"),
    path("requests/new/", views_requests.request_new, name="request_new"),
    path("requests/check/", views_requests.request_check, name="request_check"),
    path("requests/<int:pk>/withdraw/", views_requests.request_withdraw, name="request_withdraw"),
    path("new/", views.leave_add, name="add"),
    path("check/", views.leave_check, name="check"),
    path("<int:pk>/edit/", views.leave_edit, name="edit"),
    path("<int:pk>/cancel/", views.leave_cancel, name="cancel"),
    path("calendar/", views.team_calendar, name="calendar"),
    path("balances/", views.balances, name="balances"),
    path("holidays/", views.holidays, name="holidays"),
    path("settings/", views.leave_settings, name="settings"),
    path("settings/type/", views.leave_type_add, name="type_add"),
    path("settings/type/<int:pk>/", views.leave_type_edit, name="type_edit"),
    path("settings/type/<int:pk>/delete/", views.leave_type_delete, name="type_delete"),
]
