from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('voters', '0012_alter_candidate_photo'),
    ]

    operations = [
        # Add as nullable and not unique first to avoid backfill uniqueness conflicts
        migrations.AddField(
            model_name='votingsession',
            name='session_uuid',
            field=models.UUIDField(null=True, db_index=True),
        ),
        migrations.CreateModel(
            name='AnonSession',
            fields=[
                ('anon_id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('spent_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('session', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.votingsession')),
                ('voter', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to='voters.voter')),
            ],
        ),
        migrations.CreateModel(
            name='RedirectCode',
            fields=[
                ('code', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('redeemed_at', models.DateTimeField(blank=True, null=True)),
                ('expires_at', models.DateTimeField(blank=True, null=True)),
                ('anon', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.anonsession')),
                ('session', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.votingsession')),
            ],
        ),
        migrations.CreateModel(
            name='Ballot',
            fields=[
                ('ballot_id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('candidate', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.candidate')),
                ('segment', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.votingsegmentheader')),
                ('session', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.votingsession')),
            ],
        ),
        migrations.AddIndex(
            model_name='ballot',
            index=models.Index(fields=['session', 'segment'], name='voters_ballot_session_segment_idx'),
        ),
        migrations.CreateModel(
            name='EventLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(max_length=64)),
                ('payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('prev_hash', models.CharField(blank=True, max_length=64, null=True)),
                ('this_hash', models.CharField(db_index=True, max_length=64)),
                ('session', models.ForeignKey(on_delete=models.deletion.CASCADE, to='voters.votingsession')),
            ],
        ),
    ]
