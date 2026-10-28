from django.urls import path

from . import views

app_name = "leave"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("new/", views.leave_add, name="add"),
    path("check/", views.leave_check, name="check"),
    path("<int:pk>/edit/", views.leave_edit, name="edit"),
    path("<int:pk>/cancel/", views.leave_cancel, name="cancel"),
    path("employee/<int:pk>/grant/", views.grant_add, name="grant"),
    path("employee/<int:pk>/adjust/<str:start>/<str:end>/", views.grant_adjust, name="adjust"),
    path("employee/<int:pk>/carry/<str:start>/<str:end>/", views.grant_carry, name="carry"),
    path("calendar/", views.team_calendar, name="calendar"),
    path("balances/", views.balances, name="balances"),
    path("holidays/", views.holidays, name="holidays"),
    path("settings/", views.leave_settings, name="settings"),
    path("settings/type/", views.leave_type_add, name="type_add"),
    path("settings/type/<int:pk>/", views.leave_type_edit, name="type_edit"),
    path("settings/type/<int:pk>/delete/", views.leave_type_delete, name="type_delete"),
]
