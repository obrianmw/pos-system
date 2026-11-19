from django.conf import settings
from django.conf.urls.static import static
from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.urls import include, path
from django.views.generic import RedirectView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.security import admin_site_permission

admin.site.site_header = "POS System"
# Direct table editing: organization admins only (and AdminNetworkMiddleware limits it to admin networks).
admin.site.has_permission = admin_site_permission
admin.site.site_title = "POS System admin"
# "View site" goes back to the POS / back office (the controller passes its address).
admin.site.site_url = settings.WEB_APP_URL


class OrgAdminLoginForm(AdminAuthenticationForm):
    """Same sign-in as the app; say plainly who the database admin site is for."""

    error_messages = {**AdminAuthenticationForm.error_messages,
                      "invalid_login": "Wrong username or password.",
                      "invalid_login_not_admin": "Only organization admins can use the database admin site. "
                                                 "Use the back office for day-to-day work."}

    def confirm_login_allowed(self, user):
        if not admin_site_permission(type("R", (), {"user": user})()):
            raise forms.ValidationError(self.error_messages["invalid_login_not_admin"], code="not_admin")


admin.site.login_form = OrgAdminLoginForm

urlpatterns = [
    path("", RedirectView.as_view(url="/admin/", permanent=False)),  # this port is the API + database admin
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

