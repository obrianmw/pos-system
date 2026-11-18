from datetime import timedelta
from pathlib import Path
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "corsheaders",
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.inventory",
    "apps.accounting",
    "apps.payments",
    "apps.sales",
    "apps.hr",
    "apps.comms",
]

MIDDLEWARE = [
    "apps.core.security.AdminNetworkMiddleware",
    "apps.core.views.FriendlyErrorMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

_db_url = env("DATABASE_URL")
if _db_url:
    _u = urlparse(_db_url)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _u.path.lstrip("/"),
            "USER": _u.username,
            "PASSWORD": _u.password,
            "HOST": _u.hostname,
            "PORT": _u.port or 5432,
            "CONN_MAX_AGE": 60,
            "ATOMIC_REQUESTS": False,
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Blantyre"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.Pagination",
    "PAGE_SIZE": 50,
    "COERCE_DECIMAL_TO_STRING": True,
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=10),  # one shift
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

CORS_ALLOWED_ORIGINS = [o for o in env("CORS_ALLOWED_ORIGINS", "http://localhost:5180").split(",") if o]
CORS_ALLOW_HEADERS = ["authorization", "content-type", "x-branch-id"]

CELERY_BROKER_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env("CELERY_EAGER", "1" if DEBUG else "0") == "1"

DEFAULT_CURRENCY = env("DEFAULT_CURRENCY", "MWK")
PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8100")
# Where people should go instead (link on the 404 page).
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:5180/")

# ---------------------------------------------------------------------------------------------------
# Security
# The database admin site (/admin/) only answers on these networks (comma-separated CIDRs), e.g.
# "127.0.0.1/32,::1/128,10.20.0.0/24". Everyone else gets 403 before any login page.
ADMIN_ALLOWED_NETWORKS = env("ADMIN_ALLOWED_NETWORKS", "127.0.0.1/32,::1/128")
# Set to 1 when Django runs behind exactly one reverse proxy (nginx) that sets X-Forwarded-For.
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "0"))
# Name of the database owner role; the running app must not connect as it (see docker-compose.yml).
DATABASE_OWNER_USER = env("DB_OWNER_USER", "")
# Friendly page instead of Django's technical "CSRF verification failed" page.
CSRF_FAILURE_VIEW = "apps.core.views.csrf_failure"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"security": {"handlers": ["console"], "level": "WARNING"},
                # Server errors with their reference code and full traceback (never shown to users).
                "errors": {"handlers": ["console"], "level": "ERROR"}},
}

if not DEBUG:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    from apps.core.security import validate_production
    validate_production(globals())

