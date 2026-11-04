from django.urls import path

from assistant import views

app_name = "assistant"

urlpatterns = [
    path("ask/", views.ask, name="ask"),
]
