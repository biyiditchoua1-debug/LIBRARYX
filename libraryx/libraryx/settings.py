"""Django settings for the LibraryX flyer generator."""

import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent


def load_local_env_file(path):
    """Load a simple, ignored .env file without overriding host-provided env vars."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not name.isidentifier():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


load_local_env_file(BASE_DIR / ".env")


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(*names):
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


DEBUG = env_bool("DJANGO_DEBUG", default=False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "Set DJANGO_SECRET_KEY (or SECRET_KEY) to a stable, secret value in production."
        )
    SECRET_KEY = secrets.token_urlsafe(64)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if railway_domain:
        ALLOWED_HOSTS = [railway_domain]
    elif DEBUG:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
    else:
        raise ImproperlyConfigured(
            "Set DJANGO_ALLOWED_HOSTS to the production hostname(s), comma separated."
        )
if not DEBUG and "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Do not use '*' in DJANGO_ALLOWED_HOSTS in production.")

_trusted_origins = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
if _trusted_origins:
    CSRF_TRUSTED_ORIGINS = _trusted_origins
else:
    CSRF_TRUSTED_ORIGINS = []
    for host in ALLOWED_HOSTS:
        wildcard_host = host.startswith((".", "*."))
        origin_host = host[2:] if host.startswith("*.") else host.lstrip(".")
        CSRF_TRUSTED_ORIGINS.append(f"https://{origin_host}")
        if wildcard_host:
            CSRF_TRUSTED_ORIGINS.append(f"https://*.{origin_host}")
        if DEBUG:
            CSRF_TRUSTED_ORIGINS.append(f"http://{origin_host}")
            if wildcard_host:
                CSRF_TRUSTED_ORIGINS.append(f"http://*.{origin_host}")

CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
# Isolate this app's cookies from other local apps sharing 127.0.0.1.
# Browsers do not scope cookies by port, so parallel dev servers otherwise
# overwrite each other's CSRF/session cookies and can make login POSTs fail.
CSRF_COOKIE_NAME = "soutenencee_csrftoken"
SESSION_COOKIE_NAME = "soutenencee_sessionid"
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31_536_000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "generator",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "libraryx.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "libraryx.wsgi.application"


SQLITE_PATH = os.environ.get("SQLITE_PATH")
if SQLITE_PATH:
    sqlite_name = Path(SQLITE_PATH).expanduser()
else:
    sqlite_name = BASE_DIR / "db.sqlite3"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": sqlite_name,
        "OPTIONS": {"timeout": 20},
        "CONN_MAX_AGE": 0,
    }
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 9 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
ASSETS_DIR = BASE_DIR / "libraryx" / "assets"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
