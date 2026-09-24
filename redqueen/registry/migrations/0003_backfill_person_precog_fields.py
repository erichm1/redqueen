import uuid
from datetime import date

from django.db import migrations
from django.db.models import Count


def age_range(dob, today):
    if not dob:
        return ''
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years < 0:
        return ''
    for upper, label in ((17, '0-17'), (25, '18-25'), (40, '26-40'), (60, '41-60')):
        if years <= upper:
            return label
    return '60+'


def backfill(apps, schema_editor):
    Person = apps.get_model('registry', 'Person')
    today = date.today()
    for person in Person.objects.annotate(n=Count('infractions')):
        person.uuid = uuid.uuid4()  # the AddField default is evaluated once, so every row needs its own
        person.age_range = age_range(person.date_of_birth, today)
        person.total_occurrences = person.n
        person.save(update_fields=['uuid', 'age_range', 'total_occurrences'])


class Migration(migrations.Migration):
    dependencies = [('registry', '0002_person_precog_fields')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
