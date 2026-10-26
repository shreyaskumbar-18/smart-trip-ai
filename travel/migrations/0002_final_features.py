from django.db import migrations, models
import django.db.models.deletion


def _seed_existing(apps):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("travel", "Profile")
    UserPreference = apps.get_model("travel", "UserPreference")
    for user in User.objects.filter(is_active=True):
        Profile.objects.filter(user_id=user.id).update(email_verified=True)
        UserPreference.objects.get_or_create(user_id=user.id)


class Migration(migrations.Migration):
    dependencies = [("travel", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("culture", models.FloatField(default=0.5)),
                ("nature", models.FloatField(default=0.5)),
                ("adventure", models.FloatField(default=0.5)),
                ("food", models.FloatField(default=0.5)),
                ("history", models.FloatField(default=0.5)),
                ("shopping", models.FloatField(default=0.5)),
                ("relaxation", models.FloatField(default=0.5)),
                ("hidden_gems", models.FloatField(default=0.5)),
                ("sustainability", models.FloatField(default=0.5)),
                ("feedback_count", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="preference", to="auth.user")),
            ],
        ),
        migrations.CreateModel(
            name="OTPVerification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("purpose", models.CharField(choices=[("register", "Registration"), ("login", "Passwordless Login"), ("reset", "Password Reset")], max_length=20)),
                ("code_hash", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("used", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="otp_codes", to="auth.user")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Review",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.PositiveSmallIntegerField()),
                ("title", models.CharField(blank=True, max_length=120)),
                ("body", models.TextField()),
                ("helpful_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("destination", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="travel.destination")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reviews", to="auth.user")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="review",
            constraint=models.UniqueConstraint(fields=("user", "destination"), name="unique_user_destination_review"),
        ),
        migrations.RunPython(lambda apps, schema_editor: _seed_existing(apps), migrations.RunPython.noop),
    ]
