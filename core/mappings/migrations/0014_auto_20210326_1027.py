# Generated by Django 3.1.6 on 2021-03-26 10:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mappings', '0013_auto_20210115_0823'),
    ]

    operations = [
        migrations.AlterField(
            model_name='mapping',
            name='extras',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]
