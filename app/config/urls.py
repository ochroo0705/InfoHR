from accounts.views import ForcedPasswordChangeView
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", login_required(RedirectView.as_view(pattern_name="employees:list")), name="home"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/change/", ForcedPasswordChangeView.as_view(), name="password_change"),
    path("employees/", include("employees.urls")),
    path("leave/", include("leave.urls")),
    path("i18n/", include("django.conf.urls.i18n")),  # language switcher
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
