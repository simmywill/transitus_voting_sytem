# Generated by Django 5.1.2 on 2024-11-03 03:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('voters', '0003_rename_session_voter_session_id'),
    ]

    operations = [
        migrations.RenameField(
            model_name='voter',
            old_name='session_id',
            new_name='session',
        ),
    ]
