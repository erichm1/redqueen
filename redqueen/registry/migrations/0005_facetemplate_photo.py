from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('registry', '0004_person_uuid_unique')]

    operations = [
        migrations.AddField(model_name='facetemplate', name='photo',
                            field=models.FileField(blank=True, upload_to='faces/',
                                                   help_text='Cropped face image stored at enrolment (blank: template only)')),
    ]
