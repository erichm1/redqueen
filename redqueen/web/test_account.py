from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile

from cases.models import AuditEvent, SuspectProfile
from redqueen.testing import DummyWorldTestCase


class MyProfileTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.officer = User.objects.create_user('officer', password='pw', first_name='Olga', last_name='Officer',
                                               email='olga@example.org')
        cls.judge = User.objects.create_user('judge', password='pw')
        cls.judge.user_permissions.add(*Permission.objects.filter(
            codename__in=['review_profile', 'adjudicate', 'view_auditevent', 'add_person', 'delete_person']))
        cls.root = User.objects.create_superuser('root', password='pw')

    def test_requires_login(self):
        response = self.client.get('/account/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/'))

    def test_page_has_the_same_sections_as_callums_user_account_screen(self):
        self.client.force_login(self.officer)
        page = self.client.get('/account/')
        self.assertEqual(page.status_code, 200)
        for heading in ('Account', 'Groups', 'Permissions', 'About access levels', 'My activity'):
            self.assertContains(page, f'>{heading}</h2>')
        for label in ('Username', 'First name', 'Last name', 'Email', 'Active', 'Staff access', 'Superuser',
                      'Last login', 'Member since'):
            self.assertContains(page, label)
        self.assertContains(page, 'value="Olga"')
        self.assertContains(page, 'olga@example.org')
        self.assertContains(page, 'Olga Officer')

    def test_username_and_access_flags_are_read_only(self):
        self.client.force_login(self.officer)
        html = self.client.get('/account/').content.decode()
        self.assertIn('id="username" value="officer" disabled', html)
        self.assertEqual(html.count('type="checkbox" disabled'), html.count('type="checkbox"'))

    def test_status_badge(self):
        for user, badge in ((self.officer, 'Active'), (self.root, 'Superuser')):
            self.client.force_login(user)
            self.assertContains(self.client.get('/account/'), f'>{badge}</span>')
        staff = get_user_model().objects.create_user('staffer', password='pw', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get('/account/'), '>Staff</span>')

    def test_shows_groups_and_capabilities(self):
        group = Group.objects.create(name='Reviewers')
        group.permissions.add(Permission.objects.get(codename='review_profile'))
        self.officer.groups.add(group)
        self.client.force_login(self.officer)
        page = self.client.get('/account/')
        self.assertContains(page, 'Reviewers')
        can = dict(page.context['capabilities'])
        self.assertEqual((can['Review and validate suspect profiles'], can['Apply convictions and sentences']),
                         (True, False))  # review came through the group, adjudicate is not granted

        self.client.force_login(self.judge)
        can = dict(self.client.get('/account/').context['capabilities'])
        self.assertTrue(all(can.values()))

    def test_permission_list_marks_granted_and_individual_ones(self):
        self.client.force_login(self.judge)
        page = self.client.get('/account/')
        rows = {p['label']: p for p in page.context['permissions']}
        review = rows['cases | suspect profile | Can validate or reject suspect profiles'] \
            if 'cases | suspect profile | Can validate or reject suspect profiles' in rows else None
        # Meta permissions live on Judgment in this project
        review = next(p for label, p in rows.items() if 'Can validate or reject suspect profiles' in label)
        self.assertTrue(review['granted'] and review['direct'])
        not_granted = next(p for label, p in rows.items() if 'Can add intake' in label)
        self.assertFalse(not_granted['granted'])
        self.assertContains(page, '(individual)')

    def test_granted_permissions_are_listed_first_with_short_labels(self):
        self.client.force_login(self.judge)
        rows = self.client.get('/account/').context['permissions']
        flags = [r['granted'] for r in rows]
        self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertTrue(flags[0] and not flags[-1])
        self.assertFalse(any('Authentication and Authorization' in r['label'] for r in rows))

    def test_superuser_has_every_permission(self):
        self.client.force_login(self.root)
        page = self.client.get('/account/')
        self.assertTrue(all(p['granted'] for p in page.context['permissions']))
        self.assertContains(page, 'bypass all permission checks')

    def test_user_can_edit_name_and_email_and_it_is_audited(self):
        self.client.force_login(self.officer)
        response = self.client.post('/account/', {'first_name': 'Olivia', 'last_name': 'Officer', 'email': 'olivia@example.org'},
                                    follow=True)
        self.assertContains(response, 'Profile updated.')
        self.officer.refresh_from_db()
        self.assertEqual((self.officer.first_name, self.officer.email), ('Olivia', 'olivia@example.org'))
        event = AuditEvent.objects.get(action='user.profile_updated')
        self.assertEqual((event.actor, event.target), (self.officer, f'user:{self.officer.pk}'))
        self.assertEqual(sorted(event.detail['changed']), ['email', 'first_name'])

    def test_saving_without_changes_is_a_no_op(self):
        self.client.force_login(self.officer)
        response = self.client.post('/account/', {'first_name': 'Olga', 'last_name': 'Officer', 'email': 'olga@example.org'},
                                    follow=True)
        self.assertContains(response, 'Nothing to change.')
        self.assertFalse(AuditEvent.objects.filter(action='user.profile_updated').exists())

    def test_invalid_email_is_rejected_and_the_header_keeps_the_saved_name(self):
        self.client.force_login(self.officer)
        response = self.client.post('/account/', {'first_name': 'Hacker', 'last_name': 'X', 'email': 'not-an-email'})
        self.assertContains(response, 'errorlist')
        self.assertContains(response, '<h1>Olga Officer</h1>')
        self.officer.refresh_from_db()
        self.assertEqual(self.officer.first_name, 'Olga')

    def test_a_user_cannot_grant_themselves_access(self):
        self.client.force_login(self.officer)
        admin_group = Group.objects.create(name='Admins')
        self.client.post('/account/', {
            'first_name': 'Olga', 'last_name': 'Officer', 'email': 'olga@example.org',
            'is_staff': 'on', 'is_superuser': 'on', 'is_active': '', 'username': 'root',
            'groups': admin_group.pk, 'user_permissions': Permission.objects.first().pk})
        self.officer.refresh_from_db()
        self.assertEqual((self.officer.username, self.officer.is_staff, self.officer.is_superuser, self.officer.is_active),
                         ('officer', False, False, True))
        self.assertFalse(self.officer.groups.exists() or self.officer.user_permissions.exists())

    def test_the_page_is_always_the_signed_in_users_own(self):
        self.client.force_login(self.officer)
        page = self.client.get(f'/account/?user={self.judge.pk}')
        self.assertContains(page, 'officer')
        self.assertNotContains(page, 'judge')

    def test_activity_counts_and_recent_events(self):
        self.client.force_login(self.judge)
        self.client.post('/intake/new/', {'media': SimpleUploadedFile('j.png', (self.probes / 'john.png').read_bytes())})
        profile = SuspectProfile.objects.get()
        self.client.post(f'/profiles/{profile.pk}/review/', {'decision': 'reject', 'notes': 'x'})
        page = self.client.get('/account/')
        activity = page.context['activity']
        self.assertEqual((activity['intakes'], activity['reviews'], activity['judgments'], activity['logins']), (1, 1, 0, 1))
        self.assertContains(page, 'profile.reviewed')
        self.assertContains(page, 'user.login')

    def test_nav_links_to_the_profile(self):
        self.client.force_login(self.officer)
        self.assertContains(self.client.get('/'), 'href="/account/" class="whoami"')


class SignInAuditTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = get_user_model().objects.create_user('sam', password='pw')

    def test_sign_in_and_sign_out_are_logged(self):
        self.client.post('/accounts/login/', {'username': 'sam', 'password': 'pw'})
        login = AuditEvent.objects.get(action='user.login')
        self.assertEqual((login.actor, login.target), (self.user, f'user:{self.user.pk}'))
        self.client.post('/accounts/logout/')
        self.assertTrue(AuditEvent.objects.filter(action='user.logout', actor=self.user).exists())

    def test_failed_sign_in_is_logged_without_the_password(self):
        self.client.post('/accounts/login/', {'username': 'sam', 'password': 'wrong-secret'})
        event = AuditEvent.objects.get(action='user.login_failed')
        self.assertEqual(event.detail['username'], 'sam')
        self.assertNotIn('wrong-secret', str(event.detail))
        self.assertIsNone(event.actor)


class PasswordChangeTests(DummyWorldTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = get_user_model().objects.create_user('pat', password='old-Pass-123')

    def test_change_password_uses_the_app_layout_and_works(self):
        self.client.force_login(self.user)
        page = self.client.get('/accounts/password_change/')
        self.assertContains(page, 'class="brand-logo"')  # themed, not the admin's page
        response = self.client.post('/accounts/password_change/', {
            'old_password': 'old-Pass-123', 'new_password1': 'Brand-new-Pass-456', 'new_password2': 'Brand-new-Pass-456'})
        self.assertRedirects(response, '/accounts/password_change/done/')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Brand-new-Pass-456'))
        self.assertContains(self.client.get('/accounts/password_change/done/'), 'Password changed')

    def test_wrong_current_password_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post('/accounts/password_change/', {
            'old_password': 'nope', 'new_password1': 'Brand-new-Pass-456', 'new_password2': 'Brand-new-Pass-456'})
        self.assertContains(response, 'errorlist')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-Pass-123'))
