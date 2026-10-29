"""Settings for the Backend Forge API (the platform itself, not the learner's store)."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("FORGE_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("FORGE_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("FORGE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "analyzer",
    "missions",
    "runner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "forge.urls"
WSGI_APPLICATION = "forge.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "forge.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

# Where each learner session's throwaway Django project + SQLite database lives.
SANDBOX_ROOT = Path(os.environ.get("FORGE_SANDBOX_ROOT", BASE_DIR / ".sandboxes"))
# Seconds a single sandbox job (migrate / request / checks) may run before it is killed.
RUNNER_TIMEOUT = int(os.environ.get("FORGE_RUNNER_TIMEOUT", "25"))
# Largest source file accepted from the editor, in characters.
MAX_SOURCE_CHARS = 60_000
