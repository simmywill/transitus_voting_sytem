from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('voters', '0014_populate_session_uuid'),
    ]

    operations = [
        migrations.AlterField(
            model_name='votingsession',
            name='session_uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True, db_index=True, null=False),
        ),
    ]

