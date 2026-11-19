"""Branding (name, logo, colours) and printed-document settings for an organization.

GET  /api/branding/           public: name, tagline, logo and colours for the login page
GET  /api/branding/settings/  any signed-in member: everything, incl. receipt/invoice/proforma settings
PATCH /api/branding/settings/ organization admins only; multipart for the logo, clear_logo=true removes it
"""
import io
import re

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Branding, Organization, audit

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_LOGO = 3 * 1024 * 1024
LOGO_SIDE = 512


def process_logo(f):
    """Logo upload: must really be an image; keep transparency, shrink to 512 px, store as WebP."""
    if f.size > MAX_LOGO:
        raise serializers.ValidationError("Logo is larger than 3 MB.")
    try:
        img = Image.open(f)
        img.verify()
        f.seek(0)
        img = Image.open(f)
        if img.format not in ("PNG", "JPEG", "WEBP"):
            raise serializers.ValidationError("Use a PNG, JPEG or WebP logo.")
        img = ImageOps.exif_transpose(img).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise serializers.ValidationError("That file is not a readable image.")
    img.thumbnail((LOGO_SIDE, LOGO_SIDE))
    out = io.BytesIO()
    img.save(out, "WEBP", lossless=True)
    return ContentFile(out.getvalue(), name="logo.webp")


class BrandingSerializer(serializers.ModelSerializer):
    logo = serializers.ImageField(write_only=True, required=False)
    logo_url = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()

    class Meta:
        model = Branding
        exclude = ["id", "organization", "created_at"]
        read_only_fields = ["updated_at"]

    def get_logo_url(self, b):
        return b.logo.url if b.logo else None

    def get_name(self, b):
        return b.display_name or b.organization.name

    def validate_logo(self, f):
        return process_logo(f)

    def _hex(self, v):
        if not HEX.match(v or ""):
            raise serializers.ValidationError("Use a colour like #0f766e.")
        return v.lower()

    validate_primary_color = _hex
    validate_accent_color = _hex

    def validate_proforma_validity_days(self, v):
        if not 1 <= v <= 365:
            raise serializers.ValidationError("Between 1 and 365 days.")
        return v


def _org_for_public(request):
    code = request.query_params.get("org")
    qs = Organization.objects.filter(is_active=True)
    org = qs.filter(code=code).first() if code else (qs.first() if qs.count() == 1 else None)
    if org is None:
        raise NotFound("Organization not found.")
    return org


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_branding(request):
    """What the login page needs - nothing private (logos and colours are on every receipt anyway)."""
    b = Branding.for_org(_org_for_public(request))
    data = {"name": b.display_name or b.organization.name, "tagline": b.tagline,
            "logo_url": b.logo.url if b.logo else None,
            "primary_color": b.primary_color, "accent_color": b.accent_color}
    from django.conf import settings
    if getattr(settings, "DEMO_MODE", False):
        from .demo_guard import demo_accounts
        data["demo"] = demo_accounts()  # the sign-in page lists the shared demo accounts
    return Response(data)


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, MultiPartParser, FormParser])
def branding_settings(request):
    u = request.user
    if not u.organization_id:
        raise NotFound("You are not part of an organization.")
    b = Branding.for_org(u.organization)
    if request.method == "PATCH":
        if not u.has_org_perm("org.admin"):
            raise PermissionDenied("Only organization admins change branding.")
        s = BrandingSerializer(b, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        changed = sorted(k for k in s.validated_data if k != "logo")
        if request.data.get("clear_logo") in ("1", "true", True):
            b.logo.delete(save=False)
            s.save(logo="")
            changed.append("logo removed")
        else:
            s.save()
            if "logo" in s.validated_data:
                changed.append("logo")
        audit("branding.updated", organization=u.organization, actor=u, obj=b, changed=changed, request=request)
        b.refresh_from_db()
    return Response(BrandingSerializer(b).data)
