from django.db import migrations


def backfill(apps, schema_editor):
    """Existing intakes: captured_at = when they were submitted; related occurrences = every infraction of
    the people identified in them (the same rule the pipeline applies to new intakes)."""
    Intake = apps.get_model('cases', 'Intake')
    FaceMatch = apps.get_model('cases', 'FaceMatch')
    Infraction = apps.get_model('registry', 'Infraction')
    for intake in Intake.objects.all():
        intake.captured_at = intake.created_at
        intake.save(update_fields=['captured_at'])
        person_ids = set(FaceMatch.objects.filter(intake=intake, status='matched', person__isnull=False)
                         .values_list('person_id', flat=True))
        if person_ids:
            intake.related_occurrences.add(*Infraction.objects.filter(person_id__in=person_ids))


class Migration(migrations.Migration):
    dependencies = [('cases', '0004_intake_capture_details')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
