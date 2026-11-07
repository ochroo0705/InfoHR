"""Django settings for MACS Human Capital. Secrets and per-machine values come from ../.env."""

from pathlib import Path

import django_stubs_ext
import environ
from django.core.exceptions import ImproperlyConfigured
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
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])  # e.g. https://host.ts.net behind a tunnel
# Help assistant (app/assistant). Provider: claude | deepseek | gemini | groq | empty (empty = off). The key lives in .env only.
ASSISTANT_PROVIDER = env.str("ASSISTANT_PROVIDER", default="")
ASSISTANT_API_KEY = env.str("ASSISTANT_API_KEY", default="")
ASSISTANT_MODEL = env.str("ASSISTANT_MODEL", default="")
ASSISTANT_TIMEOUT = env.int("ASSISTANT_TIMEOUT", default=15)  # seconds
ASSISTANT_EXAMPLES_PER_ENTRY = env.int("ASSISTANT_EXAMPLES_PER_ENTRY", default=10)  # learned examples sent per entry
ASSISTANT_NO_ENTRY_EXAMPLES = env.int("ASSISTANT_NO_ENTRY_EXAMPLES", default=10)  # learned "no entry" questions sent
ASSISTANT_SIMILARITY = env.float("ASSISTANT_SIMILARITY", default=0.8)  # how close a test must be to an example to clash

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
    "checklists",
    "recruitment",
    "lists",
    "reports",
    "logs",
    "assistant",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "config.middleware.DefaultLanguageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.AuditContextMiddleware",
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

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["accounts.backends.LengthCheckedModelBackend"]  # Firebird: over-long usernames (see backend)

AUTH_PASSWORD_VALIDATORS = [  # user decision 2026-10-15: 8+ characters with upper, lower and a digit
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "accounts.validators.CharacterClassesValidator"},
]

LANGUAGE_CODE = "mn"
LANGUAGES = [("mn", "Монгол"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]  # compile with scripts/compile_messages.py
TIME_ZONE = "Asia/Ulaanbaatar"

# Database engine (firebird3-foundation plan, Task 10a). "postgres" = the MACS Human Capital database (default);
# "firebird" = the MACS Firebird 3 file (SQL dialect 1), where HR tables get the IHR_ prefix.
DB_ENGINE = env.str("DB_ENGINE", default="postgres")
if DB_ENGINE == "postgres":
    # Own schema "hr" in the shared info_hr database (playbook 3A: own schema next to the ERP).
    # Falls back to public only in throwaway test databases; info_hr.public is not writable by the app role.
    DATABASES = {"default": env.db("DATABASE_URL")}
    # Optional: same server and login, another database (used by scripts/demo.py for info_hr_demo).
    if env.str("DJANGO_DB_NAME", default=""):
        DATABASES["default"]["NAME"] = env.str("DJANGO_DB_NAME")
    DATABASES["default"]["OPTIONS"] = {"options": "-c search_path=hr,public"}
elif DB_ENGINE == "firebird":
    # Driver options, added only when set: the Firebird client library (default: the backend's Firebird 3
    # install path) and the SQL dialect (default 1, the dialect MACS uses).
    FIREBIRD_CLIENT_LIBRARY = env.str("FIREBIRD_CLIENT_LIBRARY", default="")
    FIREBIRD_DIALECT = env.str("FIREBIRD_DIALECT", default="")
    firebird_options = {"charset": "UTF8", "lock_timeout": 3}
    if FIREBIRD_CLIENT_LIBRARY:
        firebird_options["fb_client_library"] = FIREBIRD_CLIENT_LIBRARY
    if FIREBIRD_DIALECT:
        firebird_options["sql_dialect"] = env.int("FIREBIRD_DIALECT")
    DATABASES = {
        "default": {
            "ENGINE": "infohr_firebird",
            "HOST": env.str("FIREBIRD_HOST", default=""),
            "PORT": env.str("FIREBIRD_PORT", default=""),
            "NAME": env.str("FIREBIRD_NAME"),
            "USER": env.str("FIREBIRD_USER", default="SYSDBA"),
            "PASSWORD": env.str("FIREBIRD_PASSWORD", default=""),
            # Dialect 1 has no timezone type: with USE_TZ, times are read and written as local
            # wall-clock time in this zone, as MACS does (ruling R12). Required for Firebird.
            "TIME_ZONE": TIME_ZONE,
            "OPTIONS": firebird_options,
        }
    }
    # django.contrib.postgres is dropped and the backend app added: its system checks and fb_guard command come from it.
    INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "django.contrib.postgres"] + ["infohr_firebird"]
    # fields.E180 says the backend has no native JSON type. The backend stores JSON as text, which
    # round-trips (firebird3-foundation Task 4), so the check is silenced rather than lying in the feature flag.
    SILENCED_SYSTEM_CHECKS = ["fields.E180"]
    # models.W036 (no partial unique indexes) is emulated for the rules listed in emulated.py; E010 errors
    # for any other conditional unique constraint, so the silence cannot hide a missing rule.
    SILENCED_SYSTEM_CHECKS = [*SILENCED_SYSTEM_CHECKS, "models.W036"]
    # Firebird migration set (ruling R26): these eight apps use generated initial migrations (migrations_fb),
    # because the PostgreSQL history creates columns named with reserved words before renaming them. The
    # PostgreSQL history is never edited; macs and the contrib apps keep theirs.
    MIGRATION_MODULES = {
        "accounts": "accounts.migrations_fb",
        "lists": "lists.migrations_fb",
        "leave": "leave.migrations_fb",
        "recruitment": "recruitment.migrations_fb",
        "reports": "reports.migrations_fb",
        "employees": "employees.migrations_fb",
        "checklists": "checklists.migrations_fb",
        "assistant": "assistant.migrations_fb",
    }
else:
    raise ImproperlyConfigured(f"DB_ENGINE must be 'postgres' or 'firebird', not {DB_ENGINE!r}.")

# HR-owned table prefix in a shared database: IHR_ on Firebird (MACS already has HR_* tables), empty on PostgreSQL.
HR_TABLE_PREFIX = env.str("DJANGO_HR_TABLE_PREFIX", default="IHR_" if DB_ENGINE == "firebird" else "")
FB_GBAK = env.str("FB_GBAK", default=r"C:\Program Files\Firebird\Firebird_3_0\gbak.exe")  # cut-over backups (fb_cutover)
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
ORDER_FILES_ROOT = BASE_DIR / "private" / "orders"
ORDER_FILE_MAX_MB = 10
RECRUITMENT_FILES_ROOT = BASE_DIR / "private" / "recruitment"  # candidate CVs (app/private/ is gitignored)
ORDER_TEMPLATES_DIR = BASE_DIR.parent / "order_templates"  # Word templates of the six order types
# Request header that carries the client IP behind a reverse proxy (e.g. "HTTP_X_FORWARDED_FOR").
# Empty = use REMOTE_ADDR. Used by the system log only. The proxy must APPEND the client's IP to this
# header, not trust a value the client supplied: the last comma-separated value is the one used.
AUDIT_TRUSTED_PROXY_HEADER = ""
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
    "SITE_TITLE": "MACS Human Capital",
    "SITE_HEADER": "MACS Human Capital",
    "SITE_SUBHEADER": _("Back office"),
    "SITE_SYMBOL": "badge",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": False,
    "SHOW_LANGUAGES": True,
    # Same red as the app's "violet" scale in static/css/input.css (UI_RULES §8).
    "COLORS": {
        "primary": {
            "50": "#fdf0ee",
            "100": "#fadbd8",
            "200": "#f5b7b1",
            "300": "#f1948a",
            "400": "#ec7063",
            "500": "#e74c3c",
            "600": "#c0392b",
            "700": "#a93226",
            "800": "#922b21",
            "900": "#7b241c",
            "950": "#4a1410",
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
            {
                "title": "Тохиргоо",
                "items": [
                    {
                        "title": "Байгууллагын тохиргоо",
                        "icon": "settings",
                        "link": reverse_lazy("admin:employees_companysettings_changelist"),
                    },
                    {
                        "title": "Тушаалын загварууд",
                        "icon": "description",
                        "link": reverse_lazy("admin:employees_ordertemplate_changelist"),
                    },
                    {
                        "title": "Жагсаалтын загвар",
                        "icon": "checklist",
                        "link": reverse_lazy("admin:checklists_checklisttemplate_changelist"),
                    },
                ],
            },
            {
                "title": "Туслах",
                "items": [
                    {
                        "title": "Туслахын асуултууд",
                        "icon": "forum",
                        "link": reverse_lazy("admin:assistant_helpquestion_changelist"),
                    },
                    {
                        "title": "Сурсан жишээ, тест",
                        "icon": "school",
                        "link": reverse_lazy("admin:assistant_helpexample_changelist"),
                    },
                    {
                        "title": "Туслахын тохиргоо",
                        "icon": "tune",
                        "link": reverse_lazy("admin:assistant_assistantsettings_changelist"),
                        "permission": lambda request: request.user.has_perm("assistant.change_assistantsettings"),
                    },
                ],
            },
        ],
    },
}
