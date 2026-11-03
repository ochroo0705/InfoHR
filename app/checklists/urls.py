from django.urls import path

from checklists import views

app_name = "checklists"

urlpatterns = [
    path("task/<int:pk>/tick/", views.tick, name="tick"),
    path("task/<int:pk>/untick/", views.untick, name="untick"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("mine/", views.mine, name="mine"),
    path("employee/<int:employee_id>/start/", views.start, name="start"),
]
