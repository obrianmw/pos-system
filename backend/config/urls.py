from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.security import admin_site_permission

admin.site.site_header = "POS System"
# Direct table editing: organization admins only (and AdminNetworkMiddleware limits it to admin networks).
admin.site.has_permission = admin_site_permission
admin.site.site_title = "POS System admin"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view()),
    path("api/auth/refresh/", TokenRefreshView.as_view()),
    path("api/", include("apps.api_urls")),
]

if settings.DEBUG:  # in production the web server (nginx) serves /media/
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Friendly error pages in production. In development mode FriendlyErrorMiddleware replaces Django's
# debug pages (tracebacks, URL lists) with the same pages.
handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.not_found"
handler500 = "apps.core.views.server_error"

