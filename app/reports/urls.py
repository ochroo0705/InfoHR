from django.urls import path

from . import selection_views, views

app_name = "reports"

urlpatterns = [
    path("", views.catalogue, name="catalogue"),
    path("<slug:key>/", views.report_page, name="report"),
    path("<slug:key>/columns/", views.columns_modal, name="columns"),
    path("<slug:key>/rules/", views.rules_modal, name="rules"),
    path("<slug:key>/format/", views.format_modal, name="format"),
    path("<slug:key>/print/", views.report_print, name="print"),
    path("<slug:key>/excel/", views.report_excel, name="excel"),
    path("<slug:key>/selected/excel/", selection_views.selected_excel, name="sel_excel"),
    path("<slug:key>/selected/csv/", selection_views.selected_csv, name="sel_csv"),
    path("<slug:key>/selected/print/", selection_views.selected_print, name="sel_print"),
    path("<slug:key>/selected/copy/", selection_views.selected_copy, name="sel_copy"),
    path("<slug:key>/selected/checklist/", selection_views.selected_checklist, name="sel_checklist"),
    path("<slug:key>/views/new/", views.view_new, name="view_new"),
    path("views/<int:pk>/", views.view_edit, name="view_edit"),
    path("views/<int:pk>/delete/", views.view_delete, name="view_delete"),
]
