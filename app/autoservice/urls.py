from django.urls import path

from autoservice import views

app_name = "autoservice"

urlpatterns = [
    path("login", views.login, name="login"),
    path("logout", views.logout, name="logout"),
    path("me", views.me, name="me"),
    path("dirs", views.directory_index, name="directories"),
    path("dirs/<slug:slug>", views.directory, name="directory"),
]
