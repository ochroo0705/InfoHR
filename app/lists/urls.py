from config.converters import SignedIntConverter
from django.urls import path, register_converter

from . import views

app_name = "lists"

# Lookup-table ids can be negative (MACS test data), so the list routes take signed ids.
register_converter(SignedIntConverter, "sint")

urlpatterns = [
    path("", views.index, name="index"),
    path("meaning/", views.meaning, name="meaning"),
    path("<str:slug>/", views.list_view, name="list"),
    path("<str:slug>/add/", views.add, name="add"),
    path("<str:slug>/quick/", views.quick_add, name="quick_add"),
    path("<str:slug>/<sint:pk>/", views.edit, name="edit"),
    path("<str:slug>/<sint:pk>/delete/", views.delete, name="delete"),
]
