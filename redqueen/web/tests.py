from datetime import date
from pathlib import Path

import cv2
import numpy as np
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from cases.models import Intake, SuspectProfile
from redqueen.testing import DummyWorldTestCase
from cases.models import Intake
from registry.demographics import age_range_for
from registry.models import FaceTemplate, Infraction, Person
from vision.dummy import make_portrait


class WebTests(DummyWorldTestCase):
    bulk = 20

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.officer = User.objects.create_user('officer', password='pw')
        cls.judge = User.objects.create_user('judge', password='pw')
        cls.judge.user_permissions.add(
            *Permission.objects.filter(codename__in=['review_profile', 'adjudicate', 'view_auditevent', 'add_person', 'delete_person']))

    def upload(self, filename):
        data = (self.probes / filename).read_bytes()
        return self.client.post('/intake/new/', {'media': SimpleUploadedFile(filename, data), 'precinct': 'P-01 Harbor'})

    def test_pages_require_login(self):
        for url in ('/', '/intake/new/', '/intakes/', '/profiles/', '/people/', '/audit/'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response['Location'].startswith('/accounts/login/'), url)

    def test_login_banner_uses_bundled_art_until_you_add_your_own(self):
        from unittest import mock
        page = self.client.get('/accounts/login/')
        self.assertContains(page, 'login-banner')
        self.assertContains(page, 'web/banner.svg')
        with mock.patch('django.contrib.staticfiles.finders.find',
                        side_effect=lambda p: '/x' if p == 'web/banner.png' else None):
            self.assertContains(self.client.get('/accounts/login/'), 'web/banner.png')

    def test_login_page_and_login(self):
        self.assertContains(self.client.get('/accounts/login/'), 'Sign in')
        response = self.client.post('/accounts/login/', {'username': 'officer', 'password': 'pw'})
        self.assertRedirects(response, '/')

    def test_read_only_pages_render(self):
        self.client.force_login(self.judge)
        john = Person.objects.get(full_name='John Doe')
        for url in ('/', '/?days=365', '/intakes/', '/profiles/', '/people/', '/people/?q=jane', '/audit/',
                    '/intake/new/', f'/people/{john.pk}/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get('/'), 'COMPSTAT')
        page = self.client.get(f'/people/{john.pk}/')
        self.assertContains(page, 'HIGH risk')
        self.assertContains(page, 'more severe')
        self.assertContains(self.client.get('/people/?q=jane'), 'Jane Doe')
        self.assertNotContains(self.client.get('/people/?q=jane'), 'John Doe')

    def test_people_pages_show_the_merged_person_fields(self):
        self.client.force_login(self.officer)
        listing = self.client.get('/people/?q=john')
        self.assertContains(listing, age_range_for(date(1988, 6, 15)))
        self.assertContains(listing, 'male')
        self.assertContains(listing, 'Occurrences')
        john = Person.objects.get(full_name='John Doe')
        page = self.client.get(f'/people/{john.pk}/')
        self.assertContains(page, str(john.uuid))
        self.assertContains(page, f'age range {age_range_for(date(1988, 6, 15))}')
        self.assertContains(page, '4 occurrences')
        self.assertContains(page, 'never used in the risk outlook')

    def test_susan_has_no_risk_panel(self):
        self.client.force_login(self.officer)
        susan = Person.objects.get(full_name='Susan Doe')
        self.assertContains(self.client.get(f'/people/{susan.pk}/'), 'does not apply')

    def test_intake_upload_leads_to_profile_and_media_is_private(self):
        self.client.force_login(self.officer)
        response = self.upload('john.png')
        intake = Intake.objects.get()
        self.assertRedirects(response, f'/intakes/{intake.pk}/')
        page = self.client.get(f'/intakes/{intake.pk}/')
        self.assertContains(page, 'John Doe')
        self.assertContains(page, 'Profile #')
        self.assertEqual(self.client.get(f'/intakes/{intake.pk}/media/')['Content-Type'], 'image/png')
        self.assertEqual(self.client.get(f'/intakes/{intake.pk}/annotated/')['Content-Type'], 'image/jpeg')
        self.client.logout()
        for kind in ('media', 'annotated'):
            self.assertEqual(self.client.get(f'/intakes/{intake.pk}/{kind}/').status_code, 302)

    def test_bad_upload_shows_error(self):
        self.client.force_login(self.officer)
        response = self.client.post('/intake/new/', {'media': SimpleUploadedFile('x.png', b'garbage')})
        self.assertContains(response, 'Could not decode image')
        self.assertFalse(Intake.objects.exists())

    def test_stranger_and_clean_record_get_no_profile_link(self):
        self.client.force_login(self.officer)
        self.upload('stranger.png')
        self.upload('susan.png')
        for intake in Intake.objects.all():
            self.assertNotContains(self.client.get(f'/intakes/{intake.pk}/'), 'Profile #')

    def test_officer_cannot_review_or_judge(self):
        self.client.force_login(self.judge)
        self.upload('john.png')
        profile = SuspectProfile.objects.get()
        self.client.force_login(self.officer)
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertNotContains(page, 'Apply judgment')
        self.assertContains(page, "permission to apply judgments")
        self.assertEqual(self.client.post(f'/profiles/{profile.pk}/review/', {'decision': 'reject'}).status_code, 403)
        self.assertEqual(self.client.post(f'/profiles/{profile.pk}/judgment/', {}).status_code, 403)

    def test_judge_reviews_and_applies_judgment(self):
        self.client.force_login(self.judge)
        self.upload('john.png')
        profile = SuspectProfile.objects.get()
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertContains(page, 'Apply judgment')
        self.assertContains(page, 'Suggested')

        open_infraction = profile.person.infractions.get(status='open')
        response = self.client.post(f'/profiles/{profile.pk}/judgment/', {
            'infraction': open_infraction.pk, 'convicted': 'on', 'sentence_kind': 'probation',
            'months': 24, 'rationale': 'guideline'}, follow=True)
        self.assertContains(response, 'Judgment recorded')
        profile.refresh_from_db()
        open_infraction.refresh_from_db()
        self.assertEqual(profile.status, SuspectProfile.Status.ADJUDICATED)
        self.assertTrue(open_infraction.convicted)
        self.assertContains(self.client.get('/audit/'), 'judgment.applied')

    def test_invalid_judgment_re_renders_with_errors(self):
        self.client.force_login(self.judge)
        self.upload('john.png')
        profile = SuspectProfile.objects.get()
        response = self.client.post(f'/profiles/{profile.pk}/judgment/', {'sentence_kind': 'fine', 'amount': '-5'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'errorlist', status_code=400)
        self.assertEqual(Infraction.objects.filter(status='open', person=profile.person).count(), 1)

    def test_reject_blocks_judgment(self):
        self.client.force_login(self.judge)
        self.upload('john.png')
        profile = SuspectProfile.objects.get()
        self.client.post(f'/profiles/{profile.pk}/review/', {'decision': 'reject', 'notes': 'wrong person'})
        profile.refresh_from_db()
        self.assertEqual(profile.status, SuspectProfile.Status.REJECTED)
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertNotContains(page, 'Apply judgment')
        self.assertContains(page, 'wrong person')

    def test_audit_needs_permission(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get('/audit/').status_code, 403)

    def test_group_photo_page_shows_every_face_with_a_percentage(self):
        self.client.force_login(self.judge)
        self.upload('group.png')
        intake = Intake.objects.get()
        page = self.client.get(f'/intakes/{intake.pk}/')
        for name in ('John Doe', 'Susan Doe', 'Jane Doe', 'Mark Doe'):
            self.assertContains(page, name)
        self.assertContains(page, 'Faces found')
        self.assertContains(page, 'aria-label="Similarity ')
        self.assertContains(page, 'nothing on record')          # Susan
        self.assertContains(page, 'unknown')                    # the stranger
        self.assertEqual(page.content.decode().count('>Profile #'), 3)
        self.assertContains(page, 'threshold')
        listing = self.client.get('/intakes/')
        self.assertContains(listing, '<td>5</td>')              # faces found

    def test_person_page_lists_appearances_with_similarity(self):
        self.client.force_login(self.judge)
        self.upload('group.png')
        john = Person.objects.get(full_name='John Doe')
        page = self.client.get(f'/people/{john.pk}/')
        self.assertContains(page, 'Appearances in intakes')
        self.assertContains(page, '%</td>')


def png(name, variant=0):
    return cv2.imencode('.png', make_portrait(name, variant))[1].tobytes()


class WebcamEnrolmentTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.officer = User.objects.create_user('officer', password='pw')
        cls.judge = User.objects.create_user('judge', password='pw')
        cls.judge.user_permissions.add(*Permission.objects.filter(
            codename__in=['review_profile', 'adjudicate', 'add_person', 'delete_person']))

    def enroll(self, photos, name='Webcam Doe', scenario='escalating', **extra):
        files = [SimpleUploadedFile(f'shot{i}.png', data) for i, data in enumerate(photos)]
        return self.client.post('/people/enroll/', {'full_name': name, 'scenario': scenario, 'photos': files, **extra})

    def test_intake_and_enrol_pages_offer_the_webcam(self):
        self.client.force_login(self.judge)
        for url in ('/intake/new/', '/people/enroll/'):
            page = self.client.get(url)
            self.assertContains(page, 'data-webcam')
            self.assertContains(page, 'web/webcam.js')
        self.assertContains(self.client.get('/intake/new/'), 'Record 5 s video')
        self.assertNotContains(self.client.get('/people/enroll/'), 'Record 5 s video')
        self.assertContains(self.client.get('/people/enroll/'), 'multiple')

    def test_enrolling_needs_permission(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get('/people/enroll/').status_code, 403)
        self.assertEqual(self.enroll([png('Webcam Doe', 1)]).status_code, 403)
        self.assertNotContains(self.client.get('/people/'), 'Enroll person')

    def test_enrol_then_recognise_the_new_person_end_to_end(self):
        self.client.force_login(self.judge)
        response = self.enroll([png('Webcam Doe', 1), png('Webcam Doe', 2)], gender='non-binary',
                               date_of_birth='2001-02-03')
        person = Person.objects.get(full_name='Webcam Doe')
        self.assertEqual((person.gender, person.age_range, person.total_occurrences), ('non-binary', age_range_for(date(2001, 2, 3)), 4))
        self.assertRedirects(response, f'/people/{person.pk}/')
        self.assertEqual(FaceTemplate.objects.filter(person=person, source='webcam-enrolment').count(), 2)
        self.assertEqual(person.infractions.count(), 4)  # escalating scenario
        self.assertContains(self.client.get(f'/people/{person.pk}/'), 'HIGH risk')
        self.assertFalse(any(self._media.glob('**/shot*')))  # photos are not stored

        upload = SimpleUploadedFile('cam.png', png('Webcam Doe', 5))
        self.client.post('/intake/new/', {'media': upload})
        page = self.client.get(f'/intakes/{Intake.objects.get().pk}/')
        self.assertContains(page, 'Webcam Doe')
        self.assertContains(page, 'Profile #')

    def test_clean_scenario_gets_no_profile(self):
        self.client.force_login(self.judge)
        self.enroll([png('Clean Cam', 1)], name='Clean Cam', scenario='clean')
        self.client.post('/intake/new/', {'media': SimpleUploadedFile('c.png', png('Clean Cam', 3))})
        self.assertEqual(Intake.objects.get().status, 'no_record')

    def test_enrolment_rejections(self):
        self.client.force_login(self.judge)
        blank = cv2.imencode('.png', np.zeros((64, 64, 3), 'uint8'))[1].tobytes()
        cases = {
            'no face': ([blank], 'found 0 faces'),
            'not an image': ([b'garbage'], 'Could not decode'),
            'duplicate of John': ([png('John Doe', 4)], 'already enrolled as John Doe'),
            'too many': ([png('Many Doe', i) for i in range(1, 7)], 'At most 5'),
        }
        for label, (photos, expected) in cases.items():
            before = Person.objects.count()
            response = self.enroll(photos, name=f'X {label}')
            self.assertContains(response, expected, msg_prefix=label)
            self.assertEqual(Person.objects.count(), before, label)

    def test_delete_erases_person_faces_and_intake_media(self):
        self.client.force_login(self.judge)
        self.enroll([png('Webcam Doe', 1)])
        person = Person.objects.get(full_name='Webcam Doe')
        self.client.post('/intake/new/', {'media': SimpleUploadedFile('cam.png', png('Webcam Doe', 5))})
        media_path = Path(Intake.objects.get().media.path)
        boxes_path = Path(Intake.objects.get().annotated.path)
        self.assertTrue(media_path.exists() and boxes_path.exists())

        self.client.force_login(self.officer)
        self.assertEqual(self.client.post(f'/people/{person.pk}/delete/').status_code, 403)
        self.client.force_login(self.judge)
        self.assertEqual(self.client.get(f'/people/{person.pk}/delete/').status_code, 405)
        self.assertRedirects(self.client.post(f'/people/{person.pk}/delete/'), '/people/')
        self.assertFalse(Person.objects.filter(pk=person.pk).exists())
        self.assertFalse(FaceTemplate.objects.filter(person_id=person.pk).exists())
        self.assertFalse(Intake.objects.exists())
        self.assertFalse(media_path.exists() or boxes_path.exists())
        self.assertTrue(Person.objects.filter(full_name='John Doe').exists())  # others untouched
