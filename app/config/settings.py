"""Django settings for Info HR. Secrets and per-machine values come from ../.env."""

from pathlib import Path

import django_stubs_ext
import environ
from django.templatetags.static import static
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

django_stubs_ext.monkeypatch()  # lets admin/model classes take type parameters at runtime

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env(DJANGO_DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR.parent / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "unfold",  # admin theme; must come before django.contrib.admin
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "config.apps.HRStaticFilesConfig",  # = django.contrib.staticfiles, see config/apps.py
    "django.contrib.postgres",
    "accounts",
    "macs",
    "employees",
    "leave",
    "lists",
    "reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.DefaultLanguageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "employees.daily_sync.DailySyncMiddleware",
    "accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Own schema "hr" in the shared info_hr database (playbook 3A: own schema next to the ERP).
# Falls back to public only in throwaway test databases; info_hr.public is not writable by the app role.
DATABASES = {"default": env.db("DATABASE_URL")}
# Optional: same server and login, another database (used by scripts/demo.py for info_hr_demo).
if env.str("DJANGO_DB_NAME", default=""):
    DATABASES["default"]["NAME"] = env.str("DJANGO_DB_NAME")
DATABASES["default"]["OPTIONS"] = {"options": "-c search_path=hr,public"}

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [  # user decision 2026-10-15: 8+ characters with upper, lower and a digit
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "accounts.validators.CharacterClassesValidator"},
]

LANGUAGE_CODE = "mn"
LANGUAGES = [("mn", "Монгол"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]  # compile with scripts/compile_messages.py
TIME_ZONE = "Asia/Ulaanbaatar"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
ORDER_FILES_ROOT = BASE_DIR / "private" / "orders"
ORDER_FILE_MAX_MB = 10
ORDER_TEMPLATES_DIR = BASE_DIR.parent / "order_templates"  # Word templates of the six order types
# Fonts for the PDF of an order, first set whose four files all exist wins: (regular, bold, italic, bold italic).
# Times New Roman is the template font; the others are metric-compatible or fall-back Cyrillic fonts.
ORDER_PDF_FONT_SETS = [
    (
        "C:/Windows/Fonts/times.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
        "C:/Windows/Fonts/timesi.ttf",
        "C:/Windows/Fonts/timesbi.ttf",
    ),
    tuple(
        f"/usr/share/fonts/truetype/liberation/LiberationSerif-{s}.ttf"
        for s in ("Regular", "Bold", "Italic", "BoldItalic")
    ),
    tuple(f"/usr/share/fonts/truetype/dejavu/DejaVuSerif{s}.ttf" for s in ("", "-Bold", "-Italic", "-BoldItalic")),
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Changed static files get a new URL (hash after collectstatic, ?v=mtime otherwise): config/storage.py
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "config.storage.VersionedStaticFilesStorage"},
}

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# The admin "+" opens its add form in an iframe modal (static/js/admin_related_modal.js).
# Other sites still cannot frame us.
X_FRAME_OPTIONS = "SAMEORIGIN"

# Admin theme (django-unfold). The admin is the back office for logins and roles;
# HR staff work in the app's own screens.
UNFOLD = {
    "SITE_TITLE": "Info HR",
    "SITE_HEADER": "Info HR",
    "SITE_SUBHEADER": _("Back office"),
    "SITE_SYMBOL": "badge",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_LANGUAGES": True,
    # Same turquoise as the app's "violet" scale in static/css/input.css (UI_RULES §8).
    "COLORS": {
        "primary": {
            "50": "#eef8f8",
            "100": "#dcefef",
            "200": "#bfe0e1",
            "300": "#93cbce",
            "400": "#54aab0",
            "500": "#2b8d96",
            "600": "#0f7c86",
            "700": "#0b656e",
            "800": "#0a4f56",
            "900": "#0a3d43",
            "950": "#052a2f",
        },
    },
    "SCRIPTS": [
        lambda request: static("js/admin_related_modal.js"),  # "+" opens a modal, not a window
        lambda request: static("js/admin_effective_perms.js"),  # role permissions shown ticked on the user page
        lambda request: static("js/admin_row_click.js"),  # whole list row opens the record
        lambda request: static("js/money.js"),  # money boxes group digits by commas as typed (UI_RULES §2b)
    ],
    "SIDEBAR": {
        "show_search": False,
        "show_all_applications": False,
        "navigation": [
            {
                "title": _("Access"),
                "items": [
                    {"title": _("Users"), "icon": "person", "link": reverse_lazy("admin:accounts_user_changelist")},
                    {"title": _("Roles"), "icon": "shield_person", "link": reverse_lazy("admin:auth_group_changelist")},
                ],
            },
            {
                "title": "Ажилтан",
                "items": [
                    {
                        "title": "Хэлтсүүд",
                        "icon": "apartment",
                        "link": reverse_lazy("admin:macs_department_changelist"),
                    },
                    {
                        "title": "Албан тушаалууд",
                        "icon": "work",
                        "link": reverse_lazy("admin:macs_position_changelist"),
                    },
                ],
            },
        ],
    },
}
