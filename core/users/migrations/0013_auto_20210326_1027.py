# Generated by Django 3.1.6 on 2021-03-26 10:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0012_auto_20210304_0413'),
    ]

    operations = [
        migrations.AlterField(
            model_name='userprofile',
            name='extras',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
