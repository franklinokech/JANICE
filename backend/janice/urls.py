"""Root URL configuration. API endpoints live under /api/<version>/."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/<str:version>/", include("apps.core.urls")),
]
