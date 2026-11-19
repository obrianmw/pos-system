"""Stock-take permissions for existing default roles, and the two new default roles for every
organization (new organizations get them from DEFAULT_ROLES)."""
from django.db import migrations

ADDED = {
    "inventory.count": ["Branch Admin", "Supervisor", "Storekeeper"],
    "inventory.verify": ["Branch Admin", "Supervisor"],
}
NEW_ROLES = {
    "Stock Taker": ["inventory.view", "inventory.count"],
    "Stock Verifier": ["inventory.view", "inventory.count", "inventory.verify"],
}


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Organization = apps.get_model("core", "Organization")
    for perm, names in ADDED.items():
        for role in Role.objects.filter(name__in=names):
            if "*" not in role.permissions and perm not in role.permissions:
                role.permissions = [*role.permissions, perm]
                role.save(update_fields=["permissions"])
    for org in Organization.objects.all():
        for name, perms in NEW_ROLES.items():
            Role.objects.get_or_create(organization=org, name=name, defaults={"scope": "branch", "permissions": perms})


def revoke(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for perm in ADDED:
        for role in Role.objects.all():
            if perm in role.permissions:
                role.permissions = [p for p in role.permissions if p != perm]
                role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_stock_counts"), ("accounts", "0003_user_ui_theme"), ("core", "0003_till_users")]
    operations = [migrations.RunPython(grant, revoke)]
