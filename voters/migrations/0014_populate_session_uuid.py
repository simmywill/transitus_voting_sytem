from django.db import migrations
import uuid


def populate_session_uuid(apps, schema_editor):
    VotingSession = apps.get_model('voters', 'VotingSession')
    for vs in VotingSession.objects.all():
        if not vs.session_uuid:
            vs.session_uuid = uuid.uuid4()
            vs.save(update_fields=['session_uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('voters', '0013_session_uuid_and_anon_ballots'),
    ]

    operations = [
        migrations.RunPython(populate_session_uuid, migrations.RunPython.noop),
    ]

