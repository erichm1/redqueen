import re
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings

from web.templatetags.web_extras import gate_ornaments


class PortalFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('sam', password='pw', first_name='Sam', last_name='Rivera')

    def login(self, **extra):
        return self.client.post('/accounts/login/', {'username': 'sam', 'password': 'pw', **extra})

    def test_a_good_sign_in_goes_through_the_portal_to_the_home_page(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/portal/?next=%2F')

    def test_a_bad_sign_in_stays_on_the_form_and_never_shows_the_portal(self):
        response = self.client.post('/accounts/login/', {'username': 'sam', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sign in')
        self.assertNotContains(response, 'Accessing')

    def test_the_page_that_was_asked_for_is_kept_through_the_portal(self):
        response = self.client.get('/profiles/')
        self.assertEqual(response.status_code, 302)
        login_url = response['Location']
        self.assertIn('next=/profiles/', login_url)
        signed_in = self.client.post(login_url, {'username': 'sam', 'password': 'pw'})
        self.assertEqual(signed_in['Location'], '/portal/?next=%2Fprofiles%2F')
        page = self.client.get(signed_in['Location'])
        self.assertContains(page, 'data-destination="/profiles/"')
        self.assertContains(page, 'content="5;url=/profiles/"')

    def test_the_portal_shows_the_accessing_message_and_waits_five_seconds(self):
        self.login()
        page = self.client.get('/portal/?next=/')
        self.assertContains(page, 'Accessing')
        self.assertContains(page, 'Sam Rivera')
        self.assertContains(page, 'data-delay="5000"')
        self.assertContains(page, '<meta http-equiv="refresh" content="5;url=/">')     # also moves on without JavaScript
        for asset in ('web/portal.css', 'web/portal.js', 'web/portal3d.js', 'web/vendor/three/three.module.min.js'):
            self.assertContains(page, asset)
        self.assertNotContains(page, 'cdn')

    @override_settings(REDQUEEN={**settings.REDQUEEN, 'PORTAL_DELAY_SECONDS': 8})
    def test_the_delay_is_a_setting(self):
        self.login()
        page = self.client.get('/portal/')
        self.assertContains(page, 'data-delay="8000"')
        self.assertContains(page, 'content="8;url=/"')

    def test_the_portal_needs_a_signed_in_user(self):
        response = self.client.get('/portal/?next=/profiles/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('/accounts/login/'))

    def test_it_cannot_be_used_to_bounce_people_to_another_site(self):
        self.login()
        for evil in ('https://evil.example/steal', '//evil.example', 'http://evil.example', 'javascript:alert(1)', '/\\evil.example'):
            page = self.client.get('/portal/?next=' + quote(evil, safe=''))
            self.assertContains(page, 'data-destination="/"', msg_prefix=evil)
            self.assertNotContains(page, 'evil.example', msg_prefix=evil)
        # ... and a hostile ?next= on the sign-in form itself is dropped before it ever reaches the portal
        again = self.client.post('/accounts/login/?next=' + quote('https://evil.example', safe=''), {'username': 'sam', 'password': 'pw'})
        self.assertEqual(again['Location'], '/portal/?next=%2F')

    def test_the_portal_never_loops_back_into_itself(self):
        self.login()
        page = self.client.get('/portal/?next=' + quote('/portal/?next=/portal/', safe=''))
        self.assertContains(page, 'data-destination="/"')

    def test_a_query_string_in_the_destination_survives(self):
        self.login()
        page = self.client.get('/portal/?next=' + quote('/people/?q=doe&page=2', safe=''))
        self.assertContains(page, 'data-destination="/people/?q=doe&amp;page=2"')


class PortalShaderTests(TestCase):
    """The first design: a full-screen fire-vortex shader behind an SVG stone gate; the CSS portal is the no-WebGL fallback."""

    def test_the_vortex_is_a_fragment_shader_with_no_external_requests(self):
        js = open(finders.find('web/portal3d.js'), encoding='utf-8').read()
        for piece in ('ShaderMaterial', 'fragmentShader', 'uZoom', 'startGate'):
            self.assertIn(piece, js)
        self.assertNotIn('http', js.replace('http://www.w3.org', ''))
        self.assertIn('delay / 1000 - 0.9', js)                          # the gate swallows the screen in the last 0.9 s

    def test_the_page_maps_three_and_hides_the_css_portal_once_webgl_runs(self):
        self.client.force_login(get_user_model().objects.create_user('kim', password='pw'))
        page = self.client.get('/portal/')
        self.assertContains(page, 'web/vendor/three/three.module.min.js')
        css = open(finders.find('web/portal.css'), encoding='utf-8').read()
        self.assertIn('.portal-stage.gl-on .css-portal { display: none; }', css)


class PortalArtworkTests(TestCase):
    def test_the_gate_ornaments_are_generated_and_stable(self):
        svg = str(gate_ornaments())
        self.assertEqual((svg.count('<polyline'), svg.count('<path')), (11, 40))   # glowing cracks and runes
        self.assertEqual(svg, str(gate_ornaments()))                       # deterministic: the same gate every time
        self.assertNotRegex(svg, r'nan|inf')

    def test_the_gate_has_no_spikes_or_horns(self):
        from django.template.loader import get_template
        html = open(get_template('web/portal.html').origin.name, encoding='utf-8').read()
        self.assertNotIn('gate-horn', html)
        self.assertNotIn('<polygon', str(gate_ornaments()))
        self.assertNotIn('spike', open(finders.find('web/portal.css'), encoding='utf-8').read())
        self.assertLess(html.index('class="gate-ring"'), html.index('{% gate_ornaments %}'))   # runes sit on the ring's face

    def test_the_script_waits_exactly_the_configured_delay(self):
        js = open(finders.find('web/portal.js'), encoding='utf-8').read()
        self.assertIn('parseInt(stage.dataset.delay, 10) || 5000', js)
        self.assertRegex(js, r"setTimeout\(function \(\) \{ window\.location\.replace\(destination\); \}, delay\)")
        self.assertRegex(js, r'Math\.max\(delay - 900, 0\)')               # the zoom starts 0.9 s before the end

    def test_the_progress_bar_and_zoom_use_the_same_delay(self):
        css = open(finders.find('web/portal.css'), encoding='utf-8').read()
        self.assertIn('animation: fill var(--delay, 5s) linear forwards', css)
        self.assertIn('.portal-stage.entering .gate', css)
        self.assertIn('delay / 1000 - 0.9', open(finders.find('web/portal3d.js'), encoding='utf-8').read())

    def test_reduced_motion_keeps_the_wait_but_drops_the_motion(self):
        css = open(finders.find('web/portal.css'), encoding='utf-8').read()
        self.assertIn('prefers-reduced-motion', css)
        js = open(finders.find('web/portal.js'), encoding='utf-8').read()
        self.assertIn('if (!reduced) setTimeout', js)                      # no zoom, but the redirect timer is unconditional
