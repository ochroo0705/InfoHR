from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.catalogue, name="catalogue"),
    path("<slug:key>/", views.report_page, name="report"),
    path("<slug:key>/columns/", views.columns_modal, name="columns"),
    path("<slug:key>/print/", views.report_print, name="print"),
    path("<slug:key>/excel/", views.report_excel, name="excel"),
    path("<slug:key>/views/new/", views.view_new, name="view_new"),
    path("views/<int:pk>/", views.view_edit, name="view_edit"),
    path("views/<int:pk>/delete/", views.view_delete, name="view_delete"),
]
