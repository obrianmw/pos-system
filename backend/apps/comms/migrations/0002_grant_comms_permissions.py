"""Give the messaging permissions to existing default roles (new installs get them from DEFAULT_ROLES).
Custom roles are left alone - grant comms.send / comms.broadcast to them by hand if wanted."""
from django.db import migrations

ADDED = {
    "comms.send": ["Organization Accountant", "Organization HR", "Branch Admin", "Supervisor",
                   "Branch Accountant", "Branch HR"],
    "comms.broadcast": ["Organization HR"],
}


def grant(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for perm, names in ADDED.items():
        for role in Role.objects.filter(name__in=names):
            if "*" not in role.permissions and perm not in role.permissions:
                role.permissions = [*role.permissions, perm]
                role.save(update_fields=["permissions"])


def revoke(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for perm in ADDED:
        for role in Role.objects.all():
            if perm in role.permissions:
                role.permissions = [p for p in role.permissions if p != perm]
                role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("comms", "0001_initial"), ("accounts", "0001_initial")]
    operations = [migrations.RunPython(grant, revoke)]
