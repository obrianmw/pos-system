"""Test-only URLs: the real ones plus views that crash on purpose."""
from django.urls import path

from config.urls import urlpatterns as real


def boom(request):
    raise RuntimeError("database password is hunter2")  # must never reach the page


urlpatterns = [*real, path("boom/", boom), path("api/boom/", boom)]
