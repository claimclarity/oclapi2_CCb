# Generated by Django 4.1.7 on 2023-04-13 11:44

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('concepts', '0063_alter_concept_concept_class'),
    ]

    operations = [
        migrations.AlterField(
            model_name='concept',
            name='datatype',
            field=models.TextField(),
        ),
    ]
