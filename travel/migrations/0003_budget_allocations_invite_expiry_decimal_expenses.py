from datetime import timedelta
import secrets

from django.db import migrations, models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


def secure_existing_invites(apps, schema_editor):
    GroupTrip = apps.get_model("travel", "GroupTrip")
    now = timezone.now()
    for group in GroupTrip.objects.all().iterator():
        while True:
            code = secrets.token_urlsafe(18)
            if not GroupTrip.objects.filter(invite_code=code).exists():
                break
        group.invite_code = code
        group.invite_expires_at = now + timedelta(days=30)
        group.save(update_fields=["invite_code", "invite_expires_at"])


class Migration(migrations.Migration):
    dependencies = [("travel", "0002_final_features")]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="accommodation_budget_pct",
            field=models.PositiveSmallIntegerField(default=35, validators=[MinValueValidator(0), MaxValueValidator(100)]),
        ),
        migrations.AddField(
            model_name="trip",
            name="food_budget_pct",
            field=models.PositiveSmallIntegerField(default=25, validators=[MinValueValidator(0), MaxValueValidator(100)]),
        ),
        migrations.AddField(
            model_name="trip",
            name="transport_budget_pct",
            field=models.PositiveSmallIntegerField(default=20, validators=[MinValueValidator(0), MaxValueValidator(100)]),
        ),
        migrations.AddField(
            model_name="trip",
            name="activities_budget_pct",
            field=models.PositiveSmallIntegerField(default=15, validators=[MinValueValidator(0), MaxValueValidator(100)]),
        ),
        migrations.AddField(
            model_name="trip",
            name="miscellaneous_budget_pct",
            field=models.PositiveSmallIntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(100)]),
        ),
        migrations.AlterField(
            model_name="budgetexpense",
            name="amount",
            field=models.DecimalField(decimal_places=2, max_digits=12, validators=[MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name="grouptrip",
            name="invite_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(secure_existing_invites, migrations.RunPython.noop),
    ]
