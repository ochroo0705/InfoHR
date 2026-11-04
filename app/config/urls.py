from accounts.views import ForcedPasswordChangeView, home
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from employees.views_me import dismiss_notice, me_page

urlpatterns = [
    path("", login_required(home), name="home"),
    path("login/", auth_views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/change/", ForcedPasswordChangeView.as_view(), name="password_change"),
    path("me/", me_page, name="me"),
    path("me/notice/", dismiss_notice, name="me_notice"),
    path("employees/", include("employees.urls")),
    path("assistant/", include("assistant.urls")),
    path("leave/", include("leave.urls")),
    path("checklists/", include("checklists.urls")),
    path("recruitment/", include("recruitment.urls")),
    path("lists/", include("lists.urls")),
    path("reports/", include("reports.urls")),
    path("logs/", include("logs.urls")),
    path("i18n/", include("django.conf.urls.i18n")),  # language switcher
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
