import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from dotenv import load_dotenv


# =========================================================
# BASE
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Desarrollo local: carga .env si existe.
# Render usa las variables configuradas en Environment.
load_dotenv(BASE_DIR / ".env")


# =========================================================
# HELPERS
# =========================================================

def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_list(name, default=""):
    return [
        item.strip()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    ]


def clean_host(value):
    """
    Permite que ALLOWED_HOSTS venga como:
    hlb-e8cw.onrender.com
    https://hlb-e8cw.onrender.com
    """
    value = value.strip()

    if value in {"*", ""}:
        return value

    if "://" in value:
        value = urlparse(value).netloc

    return value.rstrip("/")


def normalize_csrf_origin(value):
    """
    CSRF_TRUSTED_ORIGINS necesita esquema.
    Si se recibe solo un hostname, en producción se asume HTTPS.
    """
    value = value.strip().rstrip("/")

    if not value:
        return ""

    if value.startswith(("http://", "https://")):
        return value

    if value.startswith(("localhost", "127.0.0.1")):
        return f"http://{value}"

    return f"https://{value}"


def postgres_config_from_url(database_url):
    """
    Convierte DATABASE_URL de Render a configuración DATABASES
    sin necesitar dj-database-url.
    """
    parsed = urlparse(database_url)

    if parsed.scheme not in {"postgres", "postgresql"}:
        raise RuntimeError(
            "DATABASE_URL debe usar postgresql:// o postgres://"
        )

    database_name = unquote(parsed.path.lstrip("/"))

    if not database_name:
        raise RuntimeError("DATABASE_URL no contiene nombre de base de datos.")

    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": database_name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 600,
        "CONN_HEALTH_CHECKS": True,
    }

    options = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if options:
        config["OPTIONS"] = options

    return config


# =========================================================
# RENDER
# =========================================================

RENDER_EXTERNAL_HOSTNAME = os.getenv(
    "RENDER_EXTERNAL_HOSTNAME",
    "",
).strip()

IS_RENDER = bool(
    os.getenv("RENDER", "").strip()
    or RENDER_EXTERNAL_HOSTNAME
)


# =========================================================
# SEGURIDAD GENERAL
# =========================================================

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "dev-only-change-me-before-production",
).strip()

# Seguro por defecto.
# En local usa DEBUG=True en tu .env.
DEBUG = env_bool("DEBUG", False)


# =========================================================
# ALLOWED HOSTS
# =========================================================

ALLOWED_HOSTS = [
    clean_host(host)
    for host in env_list(
        "ALLOWED_HOSTS",
        "localhost,127.0.0.1",
    )
]

ALLOWED_HOSTS = [
    host for host in ALLOWED_HOSTS if host
]

if (
    RENDER_EXTERNAL_HOSTNAME
    and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS
):
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


# =========================================================
# CSRF TRUSTED ORIGINS
# =========================================================

CSRF_TRUSTED_ORIGINS = [
    normalize_csrf_origin(origin)
    for origin in env_list(
        "CSRF_TRUSTED_ORIGINS",
        "",
    )
]

CSRF_TRUSTED_ORIGINS = [
    origin for origin in CSRF_TRUSTED_ORIGINS if origin
]

if RENDER_EXTERNAL_HOSTNAME:
    render_origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"

    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)


# =========================================================
# VALIDACIONES DE PRODUCCIÓN
# =========================================================

if not DEBUG:
    if (
        SECRET_KEY == "dev-only-change-me-before-production"
        or len(SECRET_KEY) < 32
    ):
        raise RuntimeError(
            "En producción debes definir SECRET_KEY con al menos "
            "32 caracteres."
        )

    if not ALLOWED_HOSTS:
        raise RuntimeError(
            "En producción debes configurar ALLOWED_HOSTS."
        )


# =========================================================
# APLICACIONES
# =========================================================

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Apps propias
    "accounts",
    "hbl_core",
]


# =========================================================
# MIDDLEWARE
# =========================================================

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",

    # WhiteNoise inmediatamente después de SecurityMiddleware.
    "whitenoise.middleware.WhiteNoiseMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# =========================================================
# URLS / WSGI / ASGI
# =========================================================

ROOT_URLCONF = "hbl_project.urls"

WSGI_APPLICATION = "hbl_project.wsgi.application"
ASGI_APPLICATION = "hbl_project.asgi.application"


# =========================================================
# TEMPLATES
# =========================================================

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",

        "DIRS": [
            BASE_DIR / "templates",
        ],

        "APP_DIRS": True,

        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",

                # Context processor del proyecto.
                # Si el 500 continúa después de este settings.py,
                # este archivo es uno de los primeros que debemos revisar:
                # hbl_core/context_processors.py
                "hbl_core.context_processors.platform",
            ],
        },
    },
]


# =========================================================
# BASE DE DATOS
# =========================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
).strip()

DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER", "").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "").strip()
DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = os.getenv("DB_PORT", "5432").strip()


# 1) Render / producción: DATABASE_URL tiene prioridad.
if DATABASE_URL:
    DATABASES = {
        "default": postgres_config_from_url(DATABASE_URL)
    }

# 2) También soporta variables PostgreSQL separadas.
elif all([
    DB_NAME,
    DB_USER,
    DB_PASSWORD,
    DB_HOST,
]):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": DB_NAME,
            "USER": DB_USER,
            "PASSWORD": DB_PASSWORD,
            "HOST": DB_HOST,
            "PORT": DB_PORT,
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
        }
    }

# 3) SQLite únicamente para desarrollo local.
elif DEBUG and not IS_RENDER:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Nunca caer silenciosamente en SQLite en Render.
else:
    raise RuntimeError(
        "No hay base de datos de producción configurada. "
        "Define DATABASE_URL o DB_NAME, DB_USER, DB_PASSWORD y DB_HOST."
    )


# =========================================================
# VALIDADORES DE CONTRASEÑA
# =========================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        )
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        )
    },
]


# =========================================================
# IDIOMA / ZONA HORARIA
# =========================================================

LANGUAGE_CODE = "es-ni"

TIME_ZONE = os.getenv(
    "TIME_ZONE",
    "America/Managua",
).strip()

USE_I18N = True
USE_TZ = True


# =========================================================
# ARCHIVOS ESTÁTICOS
# =========================================================

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Si existe una carpeta /static a nivel del proyecto, Django la incluye.
PROJECT_STATIC_DIR = BASE_DIR / "static"

STATICFILES_DIRS = (
    [PROJECT_STATIC_DIR]
    if PROJECT_STATIC_DIR.exists()
    else []
)


# =========================================================
# ARCHIVOS MEDIA
# =========================================================

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

SERVE_MEDIA = env_bool(
    "SERVE_MEDIA",
    DEBUG,
)


# =========================================================
# S3 / R2 / WASABI
# =========================================================

AWS_STORAGE_BUCKET_NAME = os.getenv(
    "AWS_STORAGE_BUCKET_NAME",
    "",
).strip()

AWS_S3_REGION_NAME = (
    os.getenv(
        "AWS_S3_REGION_NAME",
        "",
    ).strip()
    or None
)

AWS_S3_ENDPOINT_URL = (
    os.getenv(
        "AWS_S3_ENDPOINT_URL",
        "",
    ).strip()
    or None
)

AWS_S3_CUSTOM_DOMAIN = (
    os.getenv(
        "AWS_S3_CUSTOM_DOMAIN",
        "",
    ).strip()
    or None
)

AWS_ACCESS_KEY_ID = os.getenv(
    "AWS_ACCESS_KEY_ID",
    "",
).strip()

AWS_SECRET_ACCESS_KEY = os.getenv(
    "AWS_SECRET_ACCESS_KEY",
    "",
).strip()

AWS_QUERYSTRING_AUTH = env_bool(
    "AWS_QUERYSTRING_AUTH",
    False,
)

AWS_DEFAULT_ACL = None


# =========================================================
# STORAGE
# =========================================================

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },

    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage."
            "CompressedManifestStaticFilesStorage"
        ),
    },
}


# Si hay bucket configurado, utiliza almacenamiento S3-compatible.
if AWS_STORAGE_BUCKET_NAME:
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3.S3Storage",
    }

    if AWS_S3_CUSTOM_DOMAIN:
        MEDIA_URL = (
            f"https://"
            f"{AWS_S3_CUSTOM_DOMAIN.rstrip('/')}/"
        )


# =========================================================
# MODELOS
# =========================================================

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"


# =========================================================
# LOGIN
# =========================================================

LOGIN_URL = "hbl_login"


# =========================================================
# SEGURIDAD PARA RENDER / HTTPS
# =========================================================

# Render termina SSL en su proxy y envía X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_HTTPONLY = True

# Debe permanecer False si JavaScript necesita leer csrftoken
# para enviarlo en X-CSRFToken.
CSRF_COOKIE_HTTPONLY = False

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True

X_FRAME_OPTIONS = "DENY"

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# =========================================================
# HSTS
# =========================================================

SECURE_HSTS_SECONDS = (
    31536000
    if (
        not DEBUG
        and env_bool(
            "ENABLE_HSTS",
            True,
        )
    )
    else 0
)

SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    SECURE_HSTS_SECONDS > 0
)

# No usamos preload en el dominio gratuito de Render.
SECURE_HSTS_PRELOAD = False


# =========================================================
# EMAIL
# =========================================================

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
).strip()

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "HBL <no-reply@hbl.local>",
).strip()


# =========================================================
# NOWPAYMENTS · DEPÓSITOS USDT
# =========================================================

NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "").strip()
NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "").strip()
NOWPAYMENTS_API_BASE_URL = os.getenv(
    "NOWPAYMENTS_API_BASE_URL", "https://api.nowpayments.io/v1"
).strip().rstrip("/")
NOWPAYMENTS_IPN_CALLBACK_URL = os.getenv("NOWPAYMENTS_IPN_CALLBACK_URL", "").strip()
NOWPAYMENTS_TIMEOUT_SECONDS = int(os.getenv("NOWPAYMENTS_TIMEOUT_SECONDS", "15"))
NOWPAYMENTS_USER_AGENT = os.getenv(
    "NOWPAYMENTS_USER_AGENT", "HBL-Payments/1.0 (+https://hbl-e8cw.onrender.com)"
).strip()


# =========================================================
# LOGGING
# =========================================================
# Importante para que un error 500 muestre el traceback real
# en Render -> Logs, manteniendo DEBUG=False.

LOG_LEVEL = os.getenv(
    "LOG_LEVEL",
    "INFO",
).strip().upper()

APP_LOG_LEVEL = os.getenv(
    "APP_LOG_LEVEL",
    "INFO",
).strip().upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "console": {
            "format": (
                "[{asctime}] {levelname} "
                "{name}: {message}"
            ),
            "style": "{",
        },
    },

    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "console",
        },
    },

    "root": {
        "handlers": ["console"],
        "level": LOG_LEVEL,
    },

    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": LOG_LEVEL,
            "propagate": False,
        },

        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },

        "django.security": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },

        "django.db.backends": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },

        "accounts": {
            "handlers": ["console"],
            "level": APP_LOG_LEVEL,
            "propagate": False,
        },

        "hbl_core": {
            "handlers": ["console"],
            "level": APP_LOG_LEVEL,
            "propagate": False,
        },
    },
}
