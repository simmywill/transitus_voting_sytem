# Generated by Django 5.1.2 on 2024-12-03 00:49

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voters', '0007_vote'),
    ]

    operations = [
        migrations.AlterField(
            model_name='voter',
            name='session',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='voters', to='voters.votingsession'),
        ),
    ]
