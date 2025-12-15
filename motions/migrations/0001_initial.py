from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("voters", "0018_voter_email_voter_phone_number_voter_registered_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Motion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField(blank=True)),
                ("display_order", models.PositiveIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Draft"), ("open", "Open"), ("closed", "Closed")],
                        db_index=True,
                        default="draft",
                        max_length=12,
                    ),
                ),
                ("allow_vote_change", models.BooleanField(default=True)),
                ("reveal_results", models.BooleanField(default=False)),
                ("auto_close_seconds", models.PositiveIntegerField(blank=True, null=True)),
                ("opened_at", models.DateTimeField(blank=True, null=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="motions",
                        to="voters.votingsession",
                    ),
                ),
            ],
            options={
                "ordering": ["display_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="MotionVote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("voter_id", models.CharField(db_index=True, max_length=128)),
                ("choice", models.CharField(choices=[("yes", "Yes"), ("no", "No"), ("abstain", "Abstain")], max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "motion",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="votes",
                        to="motions.motion",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="motion",
            constraint=models.UniqueConstraint(
                fields=("event", "display_order"), name="uniq_motion_order_per_event"
            ),
        ),
        migrations.AddIndex(
            model_name="motionvote",
            index=models.Index(fields=["motion", "choice"], name="motions_mot_motion__9bfda0_idx"),
        ),
        migrations.AddConstraint(
            model_name="motionvote",
            constraint=models.UniqueConstraint(fields=("motion", "voter_id"), name="uniq_vote_per_motion_voter"),
        ),
    ]
