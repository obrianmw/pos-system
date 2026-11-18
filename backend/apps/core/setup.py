from apps.accounting.services import ensure_chart
from apps.accounts.models import Role
from apps.accounts.permissions_catalog import DEFAULT_ROLES


def setup_organization(org):
    """Default roles + chart of accounts for a new organization. Safe to run again."""
    for name, (scope, perms) in DEFAULT_ROLES.items():
        Role.objects.get_or_create(organization=org, name=name, defaults={"scope": scope, "permissions": perms})
    ensure_chart(org)
