from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from redqueen.testing import DummyWorldTestCase
from registry.models import Person


class ApiTests(DummyWorldTestCase):
    bulk = 20

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.officer = User.objects.create_user('officer')
        cls.judge = User.objects.create_user('judge')
        cls.judge.user_permissions.add(*Permission.objects.filter(codename__in=['review_profile', 'adjudicate']))

    def client_for(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def upload(self, client, filename, content_type='image/png'):
        data = (self.probes / filename).read_bytes()
        return client.post('/api/intakes/', {'media': SimpleUploadedFile(filename, data, content_type),
                                             'precinct': 'P-02 Midtown'}, format='multipart')

    def test_requires_authentication(self):
        self.assertEqual(self.client_for().get('/api/compstat/').status_code, 403)
        self.assertEqual(self.upload(self.client_for(), 'john.png').status_code, 403)

    def test_photo_intake_returns_faces_with_percentages_and_a_profile(self):
        response = self.upload(self.client_for(self.officer), 'john.png')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data['status'], 'profiled')
        self.assertEqual(response.data['threshold_pct'], 80.0)
        (face,) = response.data['faces']
        self.assertEqual((face['index'], face['status'], face['person_name']), (1, 'matched', 'John Doe'))
        self.assertGreater(face['similarity_pct'], 90)
        self.assertEqual(face['box'], {'x': 0, 'y': 0, 'w': 128, 'h': 128})
        self.assertEqual(len(face['candidates']), 3)
        (profile,) = response.data['profiles']
        self.assertEqual((profile['person_name'], profile['status']), ('John Doe', 'validated'))
        self.assertEqual(profile['similarity_pct'], face['similarity_pct'])
        self.assertEqual(face['profile'], profile['id'])
        self.assertEqual(len(profile['recommendations']), 1)

    def test_group_photo_returns_every_face_and_a_profile_per_suspect(self):
        response = self.upload(self.client_for(self.officer), 'group.png')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data['faces_detected'], 5)
        self.assertEqual([f['person_name'] for f in response.data['faces']],
                         ['John Doe', 'Susan Doe', None, 'Jane Doe', 'Mark Doe'])
        self.assertEqual({p['person_name'] for p in response.data['profiles']}, {'John Doe', 'Jane Doe', 'Mark Doe'})
        self.assertEqual([f['profile'] is not None for f in response.data['faces']], [True, False, False, True, True])

    def test_video_intake(self):
        response = self.upload(self.client_for(self.officer), 'mark.avi', 'video/x-msvideo')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data['media_type'], 'video')
        self.assertEqual(response.data['profiles'][0]['person_name'], 'Mark Doe')
        self.assertGreaterEqual(response.data['faces'][0]['support'], 2)

    def test_no_record_and_unknown_have_no_profile(self):
        client = self.client_for(self.officer)
        for filename, status in (('susan.png', 'no_record'), ('stranger.png', 'no_match')):
            response = self.upload(client, filename)
            self.assertEqual((response.data['status'], response.data['profiles']), (status, []))

    def test_bad_media_is_rejected(self):
        response = self.client_for(self.officer).post(
            '/api/intakes/', {'media': SimpleUploadedFile('x.png', b'not an image')}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_review_and_judgment_need_permissions(self):
        profile = self.upload(self.client_for(self.officer), 'john.png').data['profiles'][0]
        url = f'/api/profiles/{profile["id"]}'
        self.assertEqual(self.client_for(self.officer).post(f'{url}/review/', {'approve': True}).status_code, 403)
        self.assertEqual(self.client_for(self.officer).post(f'{url}/judgment/', {}).status_code, 403)

    def test_full_flow_to_conviction_and_risk(self):
        profile = self.upload(self.client_for(self.officer), 'john.png').data['profiles'][0]
        judge = self.client_for(self.judge)
        base = f'/api/profiles/{profile["id"]}'
        self.assertEqual(judge.post(f'{base}/review/', {'approve': True}, format='json').status_code, 200)
        rec = judge.get(f'{base}/').data['recommendations'][0]

        response = judge.post(f'{base}/judgment/', {
            'infraction': rec['infraction_id'], 'convicted': rec['convicted'],
            'sentence_kind': rec['sentence_kind'], 'months': rec['months'], 'rationale': 'guideline'},
            format='json')
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(judge.get(f'{base}/').data['status'], 'adjudicated')

        john = Person.objects.get(full_name='John Doe')
        risk = judge.get(f'/api/persons/{john.pk}/risk/')
        self.assertEqual(risk.status_code, 200)
        self.assertEqual((risk.data['level'], risk.data['trajectory']), ('high', 'more_severe'))
        self.assertIn('advisory', risk.data)
        # already closed -> conflict
        again = judge.post(f'{base}/judgment/', {'infraction': rec['infraction_id'], 'sentence_kind': 'warning'},
                           format='json')
        self.assertEqual(again.status_code, 409)

    def test_risk_not_applicable_without_conviction_or_fine(self):
        susan = Person.objects.get(full_name='Susan Doe')
        self.assertEqual(self.client_for(self.officer).get(f'/api/persons/{susan.pk}/risk/').status_code, 404)

    def test_compstat_endpoint(self):
        client = self.client_for(self.officer)
        response = client.get('/api/compstat/?days=28')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {'period', 'intelligence', 'tactics', 'deployment', 'follow_up'})
        self.assertEqual(client.get('/api/compstat/?days=0').status_code, 400)

    def test_swagger_schema_renders(self):
        self.assertEqual(self.client_for(self.officer).get('/swagger/?format=openapi').status_code, 200)
