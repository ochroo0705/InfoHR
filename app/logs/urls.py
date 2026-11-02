from django.urls import path

from . import views

app_name = "logs"

urlpatterns = [
    path("", views.employee_log, name="employee"),
    path("system/", views.system_log, name="system"),
    path("export/", views.employee_xlsx, name="employee_xlsx"),
    path("system/export/", views.system_xlsx, name="system_xlsx"),
]
