# Generated by Django 4.1.7 on 2023-04-13 10:49

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('concepts', '0057_remove_concept_concepts_uri_trgm_id_gin_idx_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='concept',
            name='concepts_is_late_2ce198_idx',
        ),
    ]
