"""Who may sign in to the database admin site (/admin/).

The admin site is for organization admins only (see apps.core.security). Django's admin login also needs
the user's is_staff flag, so the flags follow the role: giving someone an org-wide Organization Admin role
(or any org-wide role with "*" or "org.admin") turns admin-site access on, removing it turns it off.
Accounts outside any organization (e.g. made with `createsuperuser` for the installer) are left alone.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Membership, Role, User


def is_org_admin(user) -> bool:
    """From the memberships themselves (has_org_perm says yes to every superuser, which is circular here)."""
    if not user.is_active:
        return False
    org_wide = Membership.objects.filter(user=user, is_active=True, role__is_active=True, branch__isnull=True)
    perms = org_wide.values_list("role__permissions", flat=True)
    return any("*" in p or "org.admin" in p for p in perms)


def sync_admin_site_access(user):
    if not user.organization_id:
        return
    want = is_org_admin(user)
    if user.is_staff != want or user.is_superuser != want:
        User.objects.filter(pk=user.pk).update(is_staff=want, is_superuser=want)
        user.is_staff = user.is_superuser = want


@receiver(post_save, sender=Membership)
@receiver(post_delete, sender=Membership)
def _membership_changed(sender, instance, **kw):
    try:
        sync_admin_site_access(User.objects.get(pk=instance.user_id))
    except User.DoesNotExist:
        pass


@receiver(post_save, sender=Role)
def _role_changed(sender, instance, **kw):
    for u in User.objects.filter(memberships__role=instance).distinct():
        sync_admin_site_access(u)


@receiver(post_save, sender=User)
def _user_changed(sender, instance, update_fields=None, **kw):
    # Deactivating someone removes admin-site access too.
    if update_fields and "is_active" not in update_fields:
        return
    if instance.organization_id and instance.is_staff and not is_org_admin(instance):
        sync_admin_site_access(instance)
