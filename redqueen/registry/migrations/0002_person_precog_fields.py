import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    """Add the precog Person fields. uuid starts nullable so existing rows can be backfilled."""

    dependencies = [('registry', '0001_initial')]

    operations = [
        migrations.AddField(model_name='person', name='uuid',
                            field=models.UUIDField(null=True, editable=False, default=uuid.uuid4)),
        migrations.AddField(model_name='person', name='age_range',
                            field=models.CharField(blank=True, max_length=10, default='',
                                                   choices=[('0-17', '0-17'), ('18-25', '18-25'), ('26-40', '26-40'),
                                                            ('41-60', '41-60'), ('60+', '60+')],
                                                   help_text='Derived from the date of birth when known'),
                            preserve_default=False),
        migrations.AddField(model_name='person', name='gender',
                            field=models.CharField(blank=True, max_length=20, null=True)),
        migrations.AddField(model_name='person', name='total_occurrences',
                            field=models.PositiveIntegerField(default=0, editable=False,
                                                              help_text='Number of infractions on record (kept in sync)')),
    ]
