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

    def test_login_shows_the_animated_arcade_stage_until_you_add_your_own_banner(self):
        from unittest import mock
        page = self.client.get('/accounts/login/')
        self.assertContains(page, 'data-stage3d')
        for layer in ('wings', 'body', 'head', 'horns'):
            self.assertContains(page, f'class="layer l-{layer}"')
        for piece in ('web/queen-fx.css', 'web/stage3d.js', 'data-queen3d', 'web/queen3d.js', 'type="importmap"',
                      'web/vendor/three/three.module.min.js', 'three/addons/'):
            self.assertContains(page, piece)
        for gone in ('class="hud"', 'fight-splash', 'FIGHT!', 'hp-foe', 'VS'):  # the arcade HUD was removed on request
            self.assertNotContains(page, gone)
        self.assertNotContains(page, 'login-banner')
        with mock.patch('django.contrib.staticfiles.finders.find',
                        side_effect=lambda p: '/x' if p == 'web/banner.png' else None):
            custom = self.client.get('/accounts/login/')
        self.assertContains(custom, 'class="login-banner"')
        self.assertContains(custom, 'web/banner.png')
        self.assertNotContains(custom, 'data-stage3d')

    def test_logo_is_in_the_top_bar_and_used_as_favicon(self):
        self.client.force_login(self.officer)
        page = self.client.get('/')
        self.assertContains(page, 'class="brand-logo"')
        self.assertContains(page, 'rel="icon"')
        self.assertContains(page, 'web/logo.png')
        self.assertContains(page, 'web/favicon.png')

    def test_character_artwork_is_valid_svg_with_no_dangling_references(self):
        import re
        import xml.etree.ElementTree as ET
        from django.contrib.staticfiles import finders
        for name in ('logo.svg', 'queen.svg', 'banner.svg'):
            path = finders.find(f'web/{name}')
            self.assertIsNotNone(path, name)
            text = open(path, encoding='utf-8').read()
            root = ET.fromstring(text)  # raises if the XML is malformed
            self.assertTrue(root.tag.endswith('svg'), name)
            ids = set(re.findall(r'\bid="([^"]+)"', text))
            used = set(re.findall(r'url\(#([^)]+)\)', text))
            self.assertLessEqual(used, ids, f'{name} references undefined ids: {used - ids}')

    def test_3d_assets_are_shipped_locally_and_are_valid(self):
        import struct
        from django.contrib.staticfiles import finders
        for name in ('vendor/three/three.module.min.js', 'vendor/three/LICENSE', 'vendor/three/addons/environments/RoomEnvironment.js',
                     'vendor/three/addons/exporters/GLTFExporter.js', 'queen3d.js', 'stage3d.js'):
            path = finders.find(f'web/{name}')
            self.assertIsNotNone(path, name)
            self.assertGreater(len(open(path, 'rb').read()), 500, name)
        self.assertIn('MIT License', open(finders.find('web/vendor/three/LICENSE')).read())
        for name, size in (('logo.png', 256), ('favicon.png', 64)):
            data = open(finders.find(f'web/{name}'), 'rb').read()
            self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n', name)
            self.assertEqual(struct.unpack('>II', data[16:24]), (size, size), name)
        # nothing may load from a CDN at run time
        for name in ('queen3d.js', 'stage3d.js'):
            self.assertNotIn('http', open(finders.find(f'web/{name}')).read().replace('http://www.w3.org', ''), name)

    def test_animation_rules_match_the_artwork(self):
        """Every keyframe the rules use exists, every animated class is in the drawing, and the stage's
        shared gradients cover everything its layers reference."""
        import re
        from django.contrib.staticfiles import finders
        from django.template.loader import get_template
        css = open(finders.find('web/queen-fx.css'), encoding='utf-8').read()
        stage = open(get_template('web/_queen_stage.html').origin.name, encoding='utf-8').read()

        defined = set(re.findall(r'@keyframes\s+([\w-]+)', css))
        used = set()
        for value in re.findall(r'animation:\s*([^;}]+)', css):
            for part in value.split(','):
                used.update(w for w in part.split() if w.startswith('q-'))
        self.assertTrue(used, 'no animations found')
        self.assertLessEqual(used, defined, f'undefined keyframes: {used - defined}')
        self.assertLessEqual(defined, used, f'unused keyframes: {defined - used}')

        classes = set()
        for line in css.splitlines():
            if line.startswith('.'):  # rule heads only, not @keyframes bodies
                classes.update(re.findall(r'\.([\w-]+)', line.split('{')[0]))
        self.assertTrue({'fx-torso', 'fx-legs', 'arm-lead', 'fore-lead', 'arm-rear', 'fx-staff', 'fx-circle', 'fx-tail', 'wing'} <= classes)
        for cls in sorted(classes):
            self.assertRegex(stage, rf'class="([^"]* )?{re.escape(cls)}( [^"]*)?"', f'.{cls} is animated but not in the artwork')

        ids = set(re.findall(r'\bid="([^"]+)"', stage))
        self.assertLessEqual(set(re.findall(r'url\(#([^)]+)\)', stage)), ids)
        self.assertEqual(len(re.findall(r'<svg class="layer l-', stage)), 4)
        self.assertIn('prefers-reduced-motion', css)
        self.assertIn('svg.layer *', css)  # the reduced-motion rule must not silence the rest of the site

    def test_the_committed_artwork_is_what_the_generator_produces(self):
        import importlib.util
        import tempfile
        from pathlib import Path
        from django.contrib.staticfiles import finders
        from django.template.loader import get_template
        source = Path(__file__).resolve().parent / 'art' / 'build_queen.py'
        spec = importlib.util.spec_from_file_location('build_queen', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            static, templates = Path(tmp) / 'static', Path(tmp) / 'templates'
            templates.mkdir()
            module.build(static, templates)
            for name in ('logo.svg', 'queen.svg', 'banner.svg', 'queen-fx.css'):
                self.assertEqual((static / name).read_text(), Path(finders.find(f'web/{name}')).read_text(),
                                 f'{name} is stale: run python web/art/build_queen.py')
            self.assertEqual((templates / '_queen_stage.html').read_text(),
                             Path(get_template('web/_queen_stage.html').origin.name).read_text(),
                             '_queen_stage.html is stale: run python web/art/build_queen.py')

    def test_login_page_and_login(self):
        self.assertContains(self.client.get('/accounts/login/'), 'Sign in')
        response = self.client.post('/accounts/login/', {'username': 'officer', 'password': 'pw'})
        self.assertRedirects(response, '/portal/?next=%2F')   # sign-in passes through the hellgate portal, then opens the home page

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
        self.assertContains(page, f'<dt>Age range</dt><dd>{age_range_for(date(1988, 6, 15))}</dd>')
        self.assertContains(page, '<dt>Occurrences</dt><dd>4</dd>')
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
        import re
        self.assertEqual(len(set(re.findall(r'href="(/profiles/\d+/)"', page.content.decode()))), 3)  # 3 distinct suspects
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

    def test_enrol_page_has_the_same_fields_as_the_profile_subject_card(self):
        import re
        self.client.force_login(self.judge)
        labels = lambda html: re.findall(r'<dt>(.*?)</dt>', html)
        john = Person.objects.get(full_name='John Doe')
        profile_fields = labels(self.client.get(f'/people/{john.pk}/').content.decode())
        enrol_fields = labels(self.client.get('/people/enroll/').content.decode())
        self.assertEqual(profile_fields, ['Name', 'Person ID', 'Date of birth', 'Age range', 'Gender', 'Occurrences',
                                          'Registered', 'Face templates'])
        self.assertEqual(enrol_fields, profile_fields)
        page = self.client.get('/people/enroll/')
        for name in ('full_name', 'date_of_birth', 'age_range', 'gender', 'scenario', 'photos'):
            self.assertContains(page, f'name="{name}"')

    def test_enrol_page_previews_every_record_scenario(self):
        self.client.force_login(self.judge)
        page = self.client.get('/people/enroll/')
        for key, count in (('clean', 0), ('minor', 2), ('escalating', 4), ('desisting', 4)):
            self.assertContains(page, f'data-scenario="{key}" data-count="{count}"')
        self.assertContains(page, 'Robbery')

    def test_age_range_can_be_entered_when_the_date_of_birth_is_unknown(self):
        self.client.force_login(self.judge)
        self.enroll([png('Ageless Doe', 1)], name='Ageless Doe', scenario='clean', age_range='41-60')
        person = Person.objects.get(full_name='Ageless Doe')
        self.assertEqual((person.age_range, person.date_of_birth, person.total_occurrences), ('41-60', None, 0))

    def test_a_date_of_birth_overrides_a_conflicting_age_range(self):
        self.client.force_login(self.judge)
        self.enroll([png('Dated Doe', 1)], name='Dated Doe', date_of_birth='2015-05-05', age_range='60+')
        self.assertEqual(Person.objects.get(full_name='Dated Doe').age_range, '0-17')

    def test_invalid_age_range_is_rejected(self):
        self.client.force_login(self.judge)
        response = self.enroll([png('Bad Doe', 1)], name='Bad Doe', age_range='999')
        self.assertContains(response, 'errorlist')
        self.assertFalse(Person.objects.filter(full_name='Bad Doe').exists())

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


class ProfileDossierTests(DummyWorldTestCase):
    bulk = 0

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.officer = User.objects.create_user('officer', password='pw')
        cls.judge = User.objects.create_user('judge', password='pw')
        cls.judge.user_permissions.add(*Permission.objects.filter(
            codename__in=['review_profile', 'adjudicate', 'view_auditevent', 'add_person', 'delete_person']))

    def submit(self, filename):
        data = (self.probes / filename).read_bytes()
        self.client.post('/intake/new/', {'media': SimpleUploadedFile(filename, data), 'precinct': 'P-01 Harbor'})
        return Intake.objects.order_by('-id').first()

    def john_profile(self, filename='john.png'):
        return self.submit(filename).profiles.get(person__full_name='John Doe')

    def test_seeded_people_have_a_registered_photo(self):
        for template in FaceTemplate.objects.all():
            self.assertTrue(template.photo, template.person)
            self.assertTrue(Path(template.photo.path).exists())

    def test_profile_shows_registered_photo_and_the_intake_face_side_by_side(self):
        self.client.force_login(self.judge)
        profile = self.john_profile()
        template = profile.person.templates.get()
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertContains(page, 'Match evidence')
        self.assertContains(page, f'src="/people/{profile.person_id}/photos/{template.pk}/"')
        self.assertContains(page, f'src="/intakes/{profile.intake_id}/faces/{profile.face_match.index}/crop/"')
        self.assertContains(page, f'{profile.face_match.similarity_pct}%')
        for heading in ('Subject', 'Record summary', 'Complete record', 'Risk outlook', 'Conviction'):
            self.assertContains(page, heading)
        self.assertContains(page, str(profile.person.uuid))

    def test_photo_and_crop_endpoints_serve_jpegs_to_logged_in_users_only(self):
        self.client.force_login(self.judge)
        profile = self.john_profile()
        template = profile.person.templates.get()
        photo = self.client.get(f'/people/{profile.person_id}/photos/{template.pk}/')
        crop = self.client.get(f'/intakes/{profile.intake_id}/faces/{profile.face_match.index}/crop/')
        for response in (photo, crop):
            self.assertEqual((response.status_code, response['Content-Type']), (200, 'image/jpeg'))
        decoded = cv2.imdecode(np.frombuffer(b''.join(crop.streaming_content) if crop.streaming else crop.content,
                                             np.uint8), cv2.IMREAD_COLOR)
        self.assertIsNotNone(decoded)
        # someone else's photo id, or a face that does not exist, is a 404
        jane = Person.objects.get(full_name='Jane Doe')
        self.assertEqual(self.client.get(f'/people/{jane.pk}/photos/{template.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/intakes/{profile.intake_id}/faces/99/crop/').status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(f'/people/{profile.person_id}/photos/{template.pk}/').status_code, 302)
        self.assertEqual(self.client.get(f'/intakes/{profile.intake_id}/faces/1/crop/').status_code, 302)

    def test_video_intake_face_crop_comes_from_the_right_frame(self):
        self.client.force_login(self.judge)
        intake = self.submit('john.avi')
        face = intake.faces.filter(box_x__isnull=False).first()
        response = self.client.get(f'/intakes/{intake.pk}/faces/{face.index}/crop/')
        self.assertEqual(response.status_code, 200)

    def test_group_photo_gives_each_suspect_a_profile_with_their_own_crop(self):
        self.client.force_login(self.judge)
        intake = self.submit('group.png')
        urls = set()
        for profile in intake.profiles.all():
            page = self.client.get(f'/profiles/{profile.pk}/')
            url = f'/intakes/{intake.pk}/faces/{profile.face_match.index}/crop/'
            self.assertContains(page, url)
            urls.add(url)
        self.assertEqual(len(urls), 3)

    def test_person_without_a_stored_photo_gets_a_placeholder(self):
        self.client.force_login(self.judge)
        profile = self.john_profile()
        profile.person.templates.update(photo='')  # DB only: files on disk are not rolled back between tests
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertContains(page, 'No photo stored')
        self.assertContains(page, 'No registered photo stored')
        self.assertContains(self.client.get(f'/people/{profile.person_id}/'), 'No photo stored')

    def test_record_summary_totals(self):
        self.client.force_login(self.judge)
        page = self.client.get(f'/profiles/{self.john_profile().pk}/')
        for expected in ('<b>4</b><span>infractions (1 open)</span>', '<b>2</b><span>convictions</span>',
                         '<b>300</b><span>fines imposed', '<b>80 h</b>', '<b>12 mo</b><span>probation',
                         '<b>1 / 0</b>'):
            self.assertContains(page, expected)

    def test_profile_lists_other_appearances_and_other_profiles(self):
        self.client.force_login(self.judge)
        first = self.john_profile()
        second = self.john_profile('group.png')
        page = self.client.get(f'/profiles/{second.pk}/')
        self.assertContains(page, 'Other appearances in intakes')
        self.assertContains(page, f'/intakes/{first.intake_id}/')
        self.assertContains(page, 'Other profiles of this person')
        self.assertContains(page, f'/profiles/{first.pk}/')

    def test_audit_trail_on_the_profile_is_only_for_people_allowed_to_see_it(self):
        self.client.force_login(self.judge)
        profile = self.john_profile()
        self.assertContains(self.client.get(f'/profiles/{profile.pk}/'), 'Audit trail')
        self.assertContains(self.client.get(f'/profiles/{profile.pk}/'), 'profile.created')
        self.client.force_login(self.officer)
        self.assertNotContains(self.client.get(f'/profiles/{profile.pk}/'), 'Audit trail')

    def test_live_record_reflects_changes_after_identification(self):
        self.client.force_login(self.judge)
        profile = self.john_profile()
        from django.utils import timezone
        Infraction.objects.create(person=profile.person, category='vandalism', severity=2, occurred_at=timezone.now())
        page = self.client.get(f'/profiles/{profile.pk}/')
        self.assertContains(page, 'Vandalism')                       # in the live record
        self.assertContains(page, 'Record as it stood when this person was identified')  # frozen copy kept


class RegisteredPhotoStorageTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.judge = get_user_model().objects.create_user('judge', password='pw')
        cls.judge.user_permissions.add(*Permission.objects.filter(codename__in=['add_person', 'delete_person']))

    def enroll(self, name='Photo Doe', variants=(1, 2)):
        files = [SimpleUploadedFile(f'{i}.png', png(name, i)) for i in variants]
        return self.client.post('/people/enroll/', {'full_name': name, 'scenario': 'minor', 'photos': files})

    def test_enrolment_stores_a_cropped_face_per_template_and_shows_it(self):
        self.client.force_login(self.judge)
        self.enroll()
        person = Person.objects.get(full_name='Photo Doe')
        photos = [t.photo for t in person.templates.all()]
        self.assertEqual(len(photos), 2)
        for photo in photos:
            image = cv2.imread(photo.path)
            self.assertIsNotNone(image)
            self.assertLessEqual(max(image.shape[:2]), 320)
        page = self.client.get(f'/people/{person.pk}/')
        self.assertEqual(page.content.decode().count('/photos/'), 3)  # main + 2 thumbs
        self.assertContains(page, 'Registered photo')

    def test_photos_can_be_switched_off(self):
        from django.conf import settings
        from django.test import override_settings
        self.client.force_login(self.judge)
        with override_settings(REDQUEEN={**settings.REDQUEEN, 'STORE_ENROLMENT_PHOTOS': False}):
            self.enroll('Private Doe', variants=(1,))
        person = Person.objects.get(full_name='Private Doe')
        self.assertFalse(any(t.photo for t in person.templates.all()))
        self.assertContains(self.client.get(f'/people/{person.pk}/'), 'No photo stored')

    def test_erasing_a_person_deletes_their_photo_files_however_it_is_done(self):
        self.client.force_login(self.judge)
        self.enroll('Erase Doe', variants=(1,))
        person = Person.objects.get(full_name='Erase Doe')
        path = Path(person.templates.get().photo.path)
        self.assertTrue(path.exists())
        self.client.post(f'/people/{person.pk}/delete/')
        self.assertFalse(path.exists())

        self.enroll('Cascade Doe', variants=(1,))
        person = Person.objects.get(full_name='Cascade Doe')
        path = Path(person.templates.get().photo.path)
        person.delete()  # plain ORM cascade (as the admin does): the signal still removes the file
        self.assertFalse(path.exists())

    def test_deleting_an_intake_in_any_way_removes_its_files(self):
        self.client.force_login(self.judge)
        self.client.post('/intake/new/', {'media': SimpleUploadedFile('j.png', (self.probes / 'john.png').read_bytes())})
        intake = Intake.objects.order_by('-id').first()
        media, boxes = Path(intake.media.path), Path(intake.annotated.path)
        intake.delete()
        self.assertFalse(media.exists() or boxes.exists())
