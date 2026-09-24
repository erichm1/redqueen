import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('registry', '0003_backfill_person_precog_fields')]

    operations = [
        migrations.AlterField(model_name='person', name='uuid',
                              field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.AddIndex(model_name='person',
                            index=models.Index(fields=['age_range'], name='registry_pe_age_ran_441226_idx')),
    ]
