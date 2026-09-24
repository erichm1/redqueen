from datetime import timedelta
from pathlib import Path
from decimal import Decimal

import cv2
from django.contrib.auth import get_user_model
from django.core.files import File
from django.utils import timezone

from precog.models import RiskAssessment
from redqueen.testing import DummyWorldTestCase
from registry.models import Infraction, Penalty, Person

from . import services
from .sentencing import recommend
from vision.dummy import make_group_photo

from .models import AuditEvent, FaceMatch, Intake, SuspectProfile


class PipelineBase(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.officer = get_user_model().objects.create_user('officer')

    def submit(self, filename, precinct='P-01 Harbor'):
        with open(self.probes / filename, 'rb') as handle:
            intake = Intake(media_type='', precinct=precinct, submitted_by=self.officer)
            intake.media.save(filename, File(handle), save=False)
        return services.process_intake(intake)

    def submit_group(self, names, filename='custom-group.png'):
        cv2.imwrite(str(self.probes / filename), make_group_photo(names))
        return self.submit(filename)


class PipelineTests(PipelineBase):
    def test_person_with_record_gets_a_validated_profile(self):
        intake = self.submit('john.png')
        self.assertEqual(intake.status, Intake.Status.PROFILED)
        (face,) = intake.faces.all()
        self.assertEqual((face.person.full_name, face.status, face.index), ('John Doe', 'matched', 1))
        self.assertGreater(face.similarity_pct, 90)
        self.assertEqual(intake.threshold_pct, 80.0)
        profile = intake.profiles.get()
        self.assertEqual(profile.face_match, face)
        self.assertEqual(profile.status, SuspectProfile.Status.VALIDATED)
        self.assertEqual(len(profile.snapshot['infractions']), 4)
        self.assertTrue(all(c['passed'] for c in profile.checks))
        self.assertTrue(Path(intake.annotated.path).exists())

    def test_video_intake_is_profiled(self):
        intake = self.submit('mark.avi')
        self.assertEqual(intake.media_type, 'video')
        self.assertEqual(intake.profiles.get().person.full_name, 'Mark Doe')

    def test_clean_record_is_identified_but_not_profiled(self):
        intake = self.submit('susan.png')
        self.assertEqual(intake.status, Intake.Status.NO_RECORD)
        self.assertEqual(intake.faces.get().person.full_name, 'Susan Doe')
        self.assertFalse(SuspectProfile.objects.exists())

    def test_unknown_face_creates_nothing(self):
        intake = self.submit('stranger.png')
        self.assertEqual(intake.status, Intake.Status.NO_MATCH)
        face = intake.faces.get()
        self.assertEqual((face.status, face.person), ('no_match', None))
        self.assertLess(face.similarity_pct, 50)  # the closest registered face is still reported
        self.assertFalse(SuspectProfile.objects.exists())

    def test_future_dated_record_forces_human_review(self):
        Infraction.objects.filter(person__full_name='Jane Doe').update(
            occurred_at=timezone.now() + timedelta(days=5))
        profile = self.submit('jane.png').profiles.get()
        self.assertEqual(profile.status, SuspectProfile.Status.NEEDS_REVIEW)

    def test_judgment_requires_validated_profile_and_open_infraction(self):
        Infraction.objects.filter(person__full_name='Jane Doe').update(
            occurred_at=timezone.now() + timedelta(days=5))
        profile = self.submit('jane.png').profiles.get()
        open_infraction = profile.person.infractions.get(status='open')
        with self.assertRaises(services.PipelineError):
            services.apply_judgment(profile, open_infraction, self.officer, False, Penalty.Kind.WARNING)
        services.review_profile(profile, self.officer, approve=True)
        judgment = services.apply_judgment(profile, open_infraction, self.officer, False, Penalty.Kind.WARNING)
        with self.assertRaises(services.PipelineError):  # already closed
            services.apply_judgment(profile, open_infraction, self.officer, False, Penalty.Kind.WARNING)
        self.assertEqual(judgment.penalties.count(), 1)

    def test_rejected_profile_cannot_be_sentenced(self):
        profile = self.submit('john.png').profiles.get()
        services.review_profile(profile, self.officer, approve=False, notes='wrong person')
        with self.assertRaises(services.PipelineError):
            services.apply_judgment(profile, profile.person.infractions.get(status='open'),
                                    self.officer, True, Penalty.Kind.PROBATION, months=12)

    def test_judgment_closes_case_updates_record_and_refreshes_risk(self):
        profile = self.submit('john.png').profiles.get()
        infraction = profile.person.infractions.get(status='open')
        recommendation = services.recommendations(profile)[0]
        self.assertTrue(recommendation['convicted'])  # severity 4
        before = RiskAssessment.objects.filter(person=profile.person).count()

        services.apply_judgment(profile, infraction, self.officer, True, Penalty.Kind.PROBATION,
                                months=recommendation['months'], rationale='per guideline')

        infraction.refresh_from_db()
        profile.refresh_from_db()
        self.assertTrue(infraction.convicted)
        self.assertEqual(infraction.status, Infraction.Status.CLOSED)
        self.assertEqual(profile.status, SuspectProfile.Status.ADJUDICATED)
        self.assertEqual(infraction.penalties.get().months, recommendation['months'])
        self.assertEqual(RiskAssessment.objects.filter(person=profile.person).count(), before + 1)
        self.assertEqual(profile.person.risk_assessments.first().level, 'high')

    def test_every_step_is_audited(self):
        profile = self.submit('john.png').profiles.get()
        services.review_profile(profile, self.officer, approve=True)
        services.apply_judgment(profile, profile.person.infractions.get(status='open'), self.officer,
                                False, Penalty.Kind.FINE, amount=Decimal('100'))
        actions = list(AuditEvent.objects.values_list('action', flat=True))
        for expected in ('intake.identified', 'profile.created', 'profile.reviewed', 'judgment.applied'):
            self.assertIn(expected, actions)

    def test_sentencing_scales_with_priors(self):
        john_open = Person.objects.get(full_name='John Doe').infractions.get(status='open')
        jane_open = Person.objects.get(full_name='Jane Doe').infractions.get(status='open')
        self.assertEqual(recommend(jane_open).sentence_kind, 'fine')  # repeat minor offence
        self.assertFalse(recommend(jane_open).convicted)
        self.assertEqual(recommend(john_open).sentence_kind, 'probation')
        self.assertEqual(recommend(john_open).months, 24)  # 12 + 6 per prior conviction (2)


class GroupPhotoTests(PipelineBase):

    def test_every_suspect_in_a_group_photo_gets_a_profile(self):
        intake = self.submit('group.png')
        self.assertEqual(intake.faces_detected, 5)
        self.assertEqual(intake.status, Intake.Status.PROFILED)
        by_index = {f.index: f for f in intake.faces.select_related('person')}
        self.assertEqual([by_index[i].person.full_name if by_index[i].person else None for i in range(1, 6)],
                         ['John Doe', 'Susan Doe', None, 'Jane Doe', 'Mark Doe'])
        self.assertEqual({p.person.full_name for p in intake.profiles.all()}, {'John Doe', 'Jane Doe', 'Mark Doe'})
        self.assertTrue(all(p.status == SuspectProfile.Status.VALIDATED for p in intake.profiles.all()))
        # Susan is identified but has no record; the stranger is unknown: neither gets a profile
        self.assertFalse(SuspectProfile.objects.filter(person__full_name='Susan Doe').exists())
        self.assertEqual(by_index[3].status, 'no_match')
        for profile in intake.profiles.all():
            self.assertEqual(profile.face_match.person, profile.person)
            self.assertGreaterEqual(profile.face_match.similarity_pct, intake.threshold_pct)

    def test_group_of_people_with_no_records_or_unknown_faces(self):
        self.assertEqual(self.submit_group(['Susan Doe', 'Unknown Stranger']).status, Intake.Status.NO_RECORD)
        self.assertEqual(self.submit_group(['Unknown Stranger', 'Other Stranger']).status, Intake.Status.NO_MATCH)

    def test_suspects_from_one_photo_are_judged_independently(self):
        intake = self.submit_group(['John Doe', 'Jane Doe'])
        john, jane = (intake.profiles.get(person__full_name=n) for n in ('John Doe', 'Jane Doe'))
        for profile in (john, jane):
            rec = services.recommendations(profile)[0]
            services.apply_judgment(profile, profile.person.infractions.get(pk=rec['infraction_id']), self.officer,
                                    rec['convicted'], rec['sentence_kind'], amount=rec['amount'],
                                    hours=rec['hours'], months=rec['months'])
        self.assertEqual(SuspectProfile.objects.filter(status='adjudicated').count(), 2)
        self.assertEqual(john.person.risk_assessments.first().level, 'high')
        self.assertEqual(jane.person.risk_assessments.first().level, 'low')

    def test_same_person_matched_to_two_faces_needs_human_review(self):
        intake = self.submit_group(['John Doe', 'John Doe'])
        self.assertEqual(intake.faces.filter(person__full_name='John Doe').count(), 2)
        profile = intake.profiles.get()  # still one profile per person
        self.assertEqual(profile.status, SuspectProfile.Status.NEEDS_REVIEW)
        failed = [c['name'] for c in profile.checks if not c['passed']]
        self.assertEqual(failed, ['unique_in_frame'])

    def test_erasing_someone_in_a_group_photo_erases_the_media_but_keeps_others_profiles(self):
        intake = self.submit('group.png')
        media, boxes = Path(intake.media.path), Path(intake.annotated.path)
        jane_profile = intake.profiles.get(person__full_name='Jane Doe')
        services.delete_person(self.officer, Person.objects.get(full_name='John Doe'))
        self.assertFalse(Intake.objects.filter(pk=intake.pk).exists())
        self.assertFalse(media.exists() or boxes.exists())
        jane_profile.refresh_from_db()
        self.assertIsNone(jane_profile.intake)
        self.assertEqual(jane_profile.person.full_name, 'Jane Doe')
        self.assertFalse(SuspectProfile.objects.filter(person__full_name='John Doe').exists())
        self.assertEqual(AuditEvent.objects.get(action='person.deleted').detail['intakes_erased'], 1)
