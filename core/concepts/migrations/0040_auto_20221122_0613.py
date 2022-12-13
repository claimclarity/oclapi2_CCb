# Generated by Django 4.1.1 on 2022-11-22 06:13

from django.db import migrations


def populate_concept_id_in_localized_texts(apps, schema_editor):
    """
    1. Populates concept_id in localized_texts table using concepts_names (many-to-many).
    2. After this migration:
       - localized_texts table will have concept_id for each name
       - localized_texts without any concept_id can be deleted, as they are all descriptions which were migrated earlier
    """
    Concept = apps.get_model('concepts', 'Concept')
    LocalizedText = apps.get_model('concepts', 'LocalizedText')
    names = []
    for concept_name in Concept.names.through.objects.iterator(chunk_size=1000):
        localized_text = LocalizedText.objects.filter(id=concept_name.localizedtext_id).first()
        if localized_text:
            localized_text.concept_id = concept_name.concept_id
            names.append(localized_text)

    LocalizedText.objects.bulk_update(names, fields=['concept_id'], batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ('concepts', '0039_auto_20221122_0552'),
    ]

    operations = [
        migrations.RunPython(populate_concept_id_in_localized_texts)
    ]
