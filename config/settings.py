"""Django settings for the fuel route planner."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-not-for-production")
# A development default; set DJANGO_DEBUG=0 to turn it off.
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# A public, read-only API: there are no accounts, so no auth, session or admin apps.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "fuel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

USE_TZ = True
STATIC_URL = "static/"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

# Outside calls (routing, geocoding) are cached here. The default is per-process
# memory; point it at Redis or Memcached to share it between workers.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EXTERNAL_CACHE_SECONDS = 24 * 60 * 60

OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org")

VEHICLE_RANGE_MILES = 500
VEHICLE_MPG = 10
# A station this close to the route line counts as being on the route.
MAX_DETOUR_MILES = 5
# With an empty tank the trip starts by fuelling at the nearest station, but only if one is this close to the start.
START_STATION_MAX_MILES = 25
