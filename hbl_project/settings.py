import os
from pathlib import Path

from dotenv import load_dotenv


# =========================================================
# BASE
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga .env para desarrollo local.
# En Render se usarán las variables configuradas en Environment.
load_dotenv(BASE_DIR / ".env")


# =========================================================
# HELPERS DE VARIABLES DE ENTORNO
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


# =========================================================
# SEGURIDAD GENERAL
# =========================================================

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "dev-only-change-me-before-production",
)

# En Render debes configurar DEBUG=False.
# Para desarrollo local puedes usar DEBUG=True en tu archivo .env.
DEBUG = env_bool("DEBUG", True)


# =========================================================
# ALLOWED HOSTS
# =========================================================

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    "localhost,127.0.0.1",
)

# Render crea automáticamente esta variable.
RENDER_EXTERNAL_HOSTNAME = os.getenv(
    "RENDER_EXTERNAL_HOSTNAME",
    "",
).strip()

if (
    RENDER_EXTERNAL_HOSTNAME
    and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS
):
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


# =========================================================
# CSRF TRUSTED ORIGINS
# =========================================================

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    "",
)

# Agrega automáticamente el dominio HTTPS de Render.
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
            "En producción debes definir un SECRET_KEY fuerte "
            "(mínimo 32 caracteres)."
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

    # WhiteNoise debe ir justo después de SecurityMiddleware.
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

                # Context processor propio
                "hbl_core.context_processors.platform",
            ],
        },
    },
]


# =========================================================
# BASE DE DATOS
# =========================================================

# =========================================================
# BASE DE DATOS
# =========================================================

DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER", "").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "").strip()
DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = os.getenv("DB_PORT", "5432").strip()


# Si existen las variables PostgreSQL usamos PostgreSQL.
if all([
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

else:

    # SQLite únicamente para desarrollo local.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
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
)

USE_I18N = True
USE_TZ = True


# =========================================================
# ARCHIVOS ESTÁTICOS
# =========================================================

STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"


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


# Si hay bucket configurado, usa almacenamiento S3-compatible.
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
# BINANCE PAY
# =========================================================

BINANCE_PAY_ENABLED = env_bool(
    "BINANCE_PAY_ENABLED",
    False,
)

BINANCE_PAY_API_KEY = os.getenv(
    "BINANCE_PAY_API_KEY",
    "",
).strip()

BINANCE_PAY_SECRET_KEY = os.getenv(
    "BINANCE_PAY_SECRET_KEY",
    "",
).strip()

BINANCE_PAY_CURRENCY = os.getenv(
    "BINANCE_PAY_CURRENCY",
    "USDT",
).strip()

BINANCE_PAY_SUPPORT_CURRENCY = os.getenv(
    "BINANCE_PAY_SUPPORT_CURRENCY",
    "USDT",
).strip()

BINANCE_WEBHOOK_MAX_AGE_SECONDS = int(
    os.getenv(
        "BINANCE_WEBHOOK_MAX_AGE_SECONDS",
        "300",
    )
)


# =========================================================
# SEGURIDAD PARA RENDER / HTTPS
# =========================================================

# Render termina SSL en su proxy y envía X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = (
    "HTTP_X_FORWARDED_PROTO",
    "https",
)

# Cookies seguras en producción.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

SESSION_COOKIE_HTTPONLY = True

# Se mantiene False porque player.js utiliza csrftoken
# para peticiones POST mediante fetch().
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

# No es necesario enviar preload mientras uses
# el dominio gratuito de Render.
SECURE_HSTS_PRELOAD = False


# =========================================================
# EMAIL
# =========================================================

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    "HBL <no-reply@hbl.local>",
)