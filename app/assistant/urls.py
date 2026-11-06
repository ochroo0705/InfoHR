from django.urls import path

from assistant import views

app_name = "assistant"

urlpatterns = [
    path("ask/", views.ask, name="ask"),
    path("pick/", views.pick, name="pick"),
    path("chart/", views.chart, name="chart"),
    path("chart/xlsx/", views.chart_xlsx, name="chart_xlsx"),
]
