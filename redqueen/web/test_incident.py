import re
from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cases import services
from cases.models import Intake, SuspectProfile
from redqueen.testing import DummyWorldTestCase
from registry.models import Infraction, Person


class IncidentRecordTests(DummyWorldTestCase):
    """An intake is an incident record: when and where it was captured, who is in it, and every related occurrence."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = get_user_model().objects.create_user('officer', password='pw')

    def submit(self, filename='group.png', **fields):
        data = (self.probes / filename).read_bytes()
        response = self.client.post('/intake/new/', {'media': SimpleUploadedFile(filename, data), **fields})
        return response, Intake.objects.order_by('-id').first()

    # ---- pipeline

    def test_related_occurrences_are_all_occurrences_of_everyone_identified(self):
        self.client.force_login(self.user)
        _, intake = self.submit('group.png')
        expected = Infraction.objects.filter(person__full_name__in=['John Doe', 'Jane Doe', 'Mark Doe'])
        self.assertEqual(set(intake.related_occurrences.all()), set(expected))
        self.assertEqual(intake.related_occurrences.count(), 4 + 2 + 4)
        # Susan is identified but has none; the stranger is unknown; nobody else's records leak in
        self.assertFalse(intake.related_occurrences.exclude(person__full_name__in=['John Doe', 'Jane Doe', 'Mark Doe']).exists())

    def test_single_person_intake_relates_only_their_occurrences(self):
        self.client.force_login(self.user)
        _, intake = self.submit('jane.png')
        self.assertEqual({i.person.full_name for i in intake.related_occurrences.all()}, {'Jane Doe'})
        self.assertEqual(intake.related_occurrences.count(), 2)

    def test_no_identification_means_no_related_occurrences(self):
        self.client.force_login(self.user)
        _, intake = self.submit('stranger.png')
        self.assertEqual(intake.related_occurrences.count(), 0)

    def test_the_pipeline_audit_entry_carries_when_and_where(self):
        self.client.force_login(self.user)
        self.submit('jane.png', captured_at='2026-03-04T21:15', precinct='P-02 Midtown', location='Central Station')
        from cases.models import AuditEvent
        detail = AuditEvent.objects.get(action='intake.processed').detail
        self.assertEqual((detail['precinct'], detail['location'], detail['occurrences']), ('P-02 Midtown', 'Central Station', 2))
        self.assertTrue(detail['captured_at'].startswith('2026-03-04T21:15'))

    # ---- form

    def test_capture_details_are_stored(self):
        self.client.force_login(self.user)
        response, intake = self.submit(captured_at='2026-03-04T21:15', precinct='P-03 Old Town',
                                       location='Cathedral Square', latitude='-23.5505', longitude='-46.6333')
        self.assertRedirects(response, f'/intakes/{intake.pk}/')
        local = timezone.localtime(intake.captured_at)
        self.assertEqual((local.year, local.month, local.day, local.hour, local.minute), (2026, 3, 4, 21, 15))
        self.assertEqual((intake.precinct, intake.location, intake.latitude, intake.longitude),
                         ('P-03 Old Town', 'Cathedral Square', -23.5505, -46.6333))

    def test_capture_time_defaults_to_now(self):
        self.client.force_login(self.user)
        before = timezone.now()
        _, intake = self.submit()
        self.assertTrue(before <= intake.captured_at <= timezone.now())

    def test_the_form_is_prefilled_with_the_current_time(self):
        self.client.force_login(self.user)
        page = self.client.get('/intake/new/')
        self.assertContains(page, 'type="datetime-local"')
        self.assertRegex(page.content.decode(), r'name="captured_at"[^>]*value="\d{4}-\d\d-\d\dT\d\d:\d\d"')
        for name in ('precinct', 'location', 'latitude', 'longitude'):
            self.assertContains(page, f'name="{name}"')
        self.assertContains(page, 'Use my current location')

    def test_invalid_capture_details_are_rejected(self):
        self.client.force_login(self.user)
        future = (timezone.localtime() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        for label, fields, message in (
                ('future time', {'captured_at': future}, 'cannot be in the future'),
                ('latitude only', {'latitude': '10'}, 'both latitude and longitude'),
                ('latitude out of range', {'latitude': '95', 'longitude': '10'}, '90'),
                ('longitude out of range', {'latitude': '10', 'longitude': '200'}, '180')):
            before = Intake.objects.count()
            response, _ = self.submit(**fields)
            self.assertContains(response, message, msg_prefix=label)
            self.assertEqual(Intake.objects.count(), before, label)

    # ---- detail page

    def test_detail_page_is_a_full_incident_record(self):
        self.client.force_login(self.user)
        _, intake = self.submit(captured_at='2026-03-04T21:15', precinct='P-03 Old Town', location='Cathedral Square',
                                latitude='-23.5505', longitude='-46.6333')
        page = self.client.get(f'/intakes/{intake.pk}/')
        for heading in ('Incident record', 'Individuals involved', 'Occurrences related to this intake'):
            self.assertContains(page, heading)
        html = page.content.decode()
        self.assertIn('<dt>Date</dt><dd>2026-03-04 <span class="muted">(Wednesday)</span></dd>', html)
        self.assertRegex(html, r'<dt>Time</dt><dd class="mono">21:15:00')
        self.assertIn('<dt>Hour</dt><dd class="mono">21:00 – 21:59</dd>', html)
        self.assertContains(page, 'Cathedral Square')
        self.assertContains(page, '-23.55050, -46.63330')
        self.assertContains(page, 'openstreetmap.org/?mlat=-23.550500')
        self.assertContains(page, '<dt>Individuals</dt><dd>4 identified, 1 unidentified</dd>')
        self.assertContains(page, '<dt>Occurrences</dt><dd>10 related')

    def test_individuals_involved_lists_each_person_once_with_their_faces(self):
        self.client.force_login(self.user)
        _, intake = self.submit('group.png')
        page = self.client.get(f'/intakes/{intake.pk}/')
        section = page.content.decode().split('Individuals involved</h2>')[1].split('</section>')[0]
        for name in ('John Doe', 'Susan Doe', 'Jane Doe', 'Mark Doe'):
            self.assertEqual(section.count(f'>{name}</a>'), 1, name)
        self.assertIn('Plus 1 face that could not be identified', section)
        self.assertIn('nothing on record', section)  # Susan
        for person in Person.objects.filter(full_name__in=['John Doe', 'Susan Doe']):
            self.assertIn(str(person.uuid), section)

    def test_the_same_person_matched_twice_is_still_one_individual(self):
        import cv2
        from vision.dummy import make_group_photo
        cv2.imwrite(str(self.probes / 'twins.png'), make_group_photo(['John Doe', 'John Doe']))
        self.client.force_login(self.user)
        _, intake = self.submit('twins.png')
        self.assertEqual(self.client.get(f'/intakes/{intake.pk}/').context['identified'], 1)

    def test_occurrences_show_date_time_hour_place_and_penalties(self):
        self.client.force_login(self.user)
        _, intake = self.submit('john.png')
        page = self.client.get(f'/intakes/{intake.pk}/')
        section = page.content.decode().split('Occurrences related to this intake</h2>')[1].split('</section>')[0]
        for inf in Infraction.objects.filter(person__full_name='John Doe'):
            local = timezone.localtime(inf.occurred_at)
            self.assertIn(local.strftime('%Y-%m-%d'), section)
            self.assertIn(local.strftime('%H:%M'), section)
            self.assertIn(f'{local.hour:02d}h', section)
            self.assertIn(inf.location, section)
            self.assertIn(inf.precinct, section)
        self.assertIn('community service 80h', section)
        self.assertIn('4 occurrences', section)

    def test_hours_follow_the_configured_time_zone(self):
        self.client.force_login(self.user)
        intake = Intake(precinct='P-01 Harbor', captured_at=datetime(2026, 5, 6, 15, 0, tzinfo=dt_timezone.utc))
        intake.media.save('x.png', ContentFile((self.probes / 'jane.png').read_bytes()), save=False)
        intake = services.process_intake(intake)
        with override_settings(TIME_ZONE='America/Sao_Paulo'):
            html = self.client.get(f'/intakes/{intake.pk}/').content.decode()
        self.assertIn('<dt>Hour</dt><dd class="mono">12:00 – 12:59</dd>', html)
        self.assertRegex(html, r'<dt>Time</dt><dd class="mono">12:00:00 <span class="muted">America/Sao_Paulo')
        with override_settings(TIME_ZONE='UTC'):
            self.assertIn('15:00 – 15:59', self.client.get(f'/intakes/{intake.pk}/').content.decode())

    # ---- list and record tables

    def test_intake_list_shows_capture_time_hour_location_and_counts(self):
        self.client.force_login(self.user)
        self.submit('group.png', captured_at='2026-03-04T21:15', precinct='P-03 Old Town', location='Cathedral Square')
        row = self.client.get('/intakes/').content.decode().split('<tbody>')[1]
        for expected in ('2026-03-04 21:15', '21h', 'P-03 Old Town', 'Cathedral Square'):
            self.assertIn(expected, row)
        self.assertRegex(row, r'<td>5</td><td>4</td><td>10</td><td>3</td>')  # faces, individuals, occurrences, profiles

    def test_intakes_are_listed_by_capture_time_not_submission_time(self):
        self.client.force_login(self.user)
        self.submit('jane.png', captured_at='2026-01-01T08:00')
        self.submit('john.png', captured_at='2026-02-01T08:00')
        self.submit('mark.avi', captured_at='2025-12-01T08:00')
        stamps = re.findall(r'(\d{4}-\d\d-\d\d) \d\d:\d\d</td><td class="mono">\d\dh', self.client.get('/intakes/').content.decode())
        self.assertEqual(stamps, ['2026-02-01', '2026-01-01', '2025-12-01'])

    def test_profile_and_person_records_show_time_and_place(self):
        self.client.force_login(self.user)
        _, intake = self.submit('john.png')
        profile = intake.profiles.get()
        inf = Infraction.objects.filter(person=profile.person).first()
        for url in (f'/profiles/{profile.pk}/', f'/people/{profile.person_id}/'):
            html = self.client.get(url).content.decode()
            self.assertIn('<th>Time</th>', html)
            self.assertIn('<th>Location</th>', html)
            self.assertIn(inf.location, html)
            self.assertIn(timezone.localtime(inf.occurred_at).strftime('%H:%M'), html)

    def test_dummy_occurrences_all_have_a_place(self):
        self.assertFalse(Infraction.objects.filter(location='').exists())
        self.assertTrue(all(i.location for i in Infraction.objects.filter(person__full_name='John Doe')))
        self.assertEqual({i['location'] != '' for i in services.record_snapshot(
            Person.objects.get(full_name='John Doe'))['infractions']}, {True})


class IncidentApiTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = get_user_model().objects.create_user('officer', password='pw')

    def post(self, filename='group.png', **fields):
        client = APIClient()
        client.force_authenticate(self.user)
        data = (self.probes / filename).read_bytes()
        return client.post('/api/intakes/', {'media': SimpleUploadedFile(filename, data), **fields}, format='multipart')

    def test_response_is_a_full_incident_record(self):
        response = self.post(captured_at='2026-03-04T21:15:30Z', precinct='P-03 Old Town', location='Cathedral Square',
                             latitude='-23.5505', longitude='-46.6333')
        self.assertEqual(response.status_code, 201, response.content)
        data = response.data
        self.assertEqual((data['location'], data['precinct'], data['latitude'], data['longitude']),
                         ('Cathedral Square', 'P-03 Old Town', -23.5505, -46.6333))
        local = timezone.localtime(datetime(2026, 3, 4, 21, 15, 30, tzinfo=dt_timezone.utc))
        self.assertEqual((data['date'], data['time'], data['hour']),
                         (local.date().isoformat(), local.strftime('%H:%M:%S'), local.hour))

        who = data['individuals']
        self.assertEqual(sorted(p['name'] for p in who['identified']), ['Jane Doe', 'John Doe', 'Mark Doe', 'Susan Doe'])
        self.assertEqual(who['unidentified_faces'], 1)
        john = next(p for p in who['identified'] if p['name'] == 'John Doe')
        self.assertEqual((john['faces'], john['occurrences']), ([1], 4))
        self.assertIsNotNone(john['profile'])
        self.assertIsNone(next(p for p in who['identified'] if p['name'] == 'Susan Doe')['profile'])

        occurrences = data['occurrences']
        self.assertEqual(len(occurrences), 10)
        first = occurrences[0]
        for key in ('id', 'person', 'person_name', 'category', 'severity', 'occurred_at', 'date', 'time', 'hour',
                    'precinct', 'location', 'status', 'convicted', 'penalties'):
            self.assertIn(key, first)
        self.assertTrue(all(o['location'] for o in occurrences))

    def test_capture_time_defaults_to_now_and_can_be_read_back(self):
        created = self.post('jane.png')
        self.assertEqual(created.status_code, 201)
        client = APIClient()
        client.force_authenticate(self.user)
        again = client.get(f'/api/intakes/{created.data["id"]}/').data
        self.assertEqual(again['captured_at'], created.data['captured_at'])
        self.assertEqual(len(again['occurrences']), 2)

    def test_invalid_capture_details_are_rejected(self):
        future = (timezone.now() + timedelta(days=3)).isoformat()
        for fields in ({'captured_at': future}, {'latitude': '10'}, {'latitude': '95', 'longitude': '10'}):
            self.assertEqual(self.post('jane.png', **fields).status_code, 400, fields)
