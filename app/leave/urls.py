from django.urls import path

from . import views

app_name = "leave"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("new/", views.leave_add, name="add"),
    path("check/", views.leave_check, name="check"),
    path("<int:pk>/edit/", views.leave_edit, name="edit"),
    path("<int:pk>/cancel/", views.leave_cancel, name="cancel"),
    path("employee/<int:pk>/adjust/<str:year>/", views.grant_adjust, name="adjust"),
    path("employee/<int:pk>/carry/<str:year>/", views.grant_carry, name="carry"),
    path("calendar/", views.team_calendar, name="calendar"),
    path("holidays/", views.holidays, name="holidays"),
]
