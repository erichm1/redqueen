"""Every entity in the unified project: it can be created by the pipeline, read, shown in the admin,
and the models match the migrations."""
from datetime import date

import cv2
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.files import File

from cases import services
from cases.models import Intake
from redqueen.testing import DummyWorldTestCase
from registry.demographics import age_range_for

FIRST_PARTY = ('registry', 'cases', 'precog')


def first_party_models():
    return [m for label in FIRST_PARTY for m in apps.get_app_config(label).get_models()]


class EntityHealthTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = get_user_model().objects.create_superuser('root', password='pw')
        # drive the whole pipeline so that every entity has at least one row
        intake = Intake(precinct='P-01 Harbor', submitted_by=cls.admin)
        with open(cls._media / 'dummy' / 'group.png', 'rb') as handle:
            intake.media.save('group.png', File(handle), save=False)
        services.process_intake(intake)
        profile = intake.profiles.get(person__full_name='John Doe')
        services.review_profile(profile, cls.admin, approve=True, notes='entity check')
        rec = services.recommendations(profile)[0]
        services.apply_judgment(profile, profile.person.infractions.get(pk=rec['infraction_id']), cls.admin,
                                rec['convicted'], rec['sentence_kind'], months=rec['months'])

    def test_every_entity_is_covered(self):
        self.assertEqual(
            sorted(m.__name__ for m in first_party_models()),
            ['AuditEvent', 'FaceMatch', 'FaceTemplate', 'Infraction', 'Intake', 'Judgment', 'Penalty',
             'Person', 'RiskAssessment', 'SuspectProfile'])

    def test_every_entity_has_data_and_a_readable_name(self):
        for model in first_party_models():
            instance = model.objects.first()
            self.assertIsNotNone(instance, f'{model.__name__} has no rows: extend the scenario above')
            self.assertNotIn(' object (', str(instance), model.__name__)

    def test_every_entity_is_editable_in_the_admin(self):
        self.client.force_login(self.admin)
        for model in first_party_models():
            base = f'/admin/{model._meta.app_label}/{model._meta.model_name}/'
            self.assertEqual(self.client.get(base).status_code, 200, f'{model.__name__} changelist')
            self.assertEqual(self.client.get(base + 'add/').status_code, 200, f'{model.__name__} add form')
            pk = model.objects.first().pk
            self.assertEqual(self.client.get(f'{base}{pk}/change/').status_code, 200, f'{model.__name__} change form')

    def test_stored_rows_pass_model_validation(self):
        for model in first_party_models():
            for instance in model.objects.all()[:5]:
                instance.full_clean(exclude=['media', 'annotated'])  # file fields are validated on upload

    def test_person_relations_all_hang_together(self):
        from registry.models import Person
        john = Person.objects.get(full_name='John Doe')
        self.assertEqual(john.total_occurrences, john.infractions.count())
        self.assertTrue(john.templates.exists() and john.face_matches.exists() and john.profiles.exists())
        self.assertTrue(john.risk_assessments.exists())
        self.assertEqual(john.age_range, age_range_for(date(1988, 6, 15)))

    def test_models_match_migrations(self):
        call_command('makemigrations', '--check', '--dry-run', verbosity=0)
