"""The RED QUEEN wordmark is full blood red and glowing wherever it sits next to the logo."""
import re

from django.contrib.staticfiles import finders
from django.test import Client, SimpleTestCase


def css():
    return open(finders.find('web/style.css'), encoding='utf-8').read()


def rule(selector, text):
    return re.search(re.escape(selector) + r' \{([^}]*)\}', text, flags=re.S).group(1)


class BloodRedWordmarkTests(SimpleTestCase):
    def test_the_blood_colour_is_a_deep_saturated_red(self):
        blood = re.search(r'--blood: #([0-9a-f]{6})', css()).group(1)
        r, g, b = (int(blood[i:i + 2], 16) for i in (0, 2, 4))
        self.assertGreater(r, 180)                 # bright enough to glow on the dark background
        self.assertLess(g, 40)
        self.assertLess(b, 40)                     # ... and still blood, not pink or orange

    def test_both_words_on_the_sign_in_banner_are_blood_red_and_glow(self):
        text = css()
        words = rule('.stage-text .w1, .stage-text .w2', text)
        self.assertIn('color: var(--blood)', words)
        self.assertIn('text-shadow', words)
        self.assertIn('animation: blood-glow', words)
        self.assertNotIn('var(--text)', words)     # RED used to be white
        self.assertIn('@keyframes blood-glow', text)

    def test_the_top_bar_name_is_blood_red_and_glows_too(self):
        brand = rule('.brand', css())
        self.assertIn('color: var(--blood)', brand)
        self.assertIn('text-shadow', brand)

    def test_the_glow_stops_for_reduced_motion_but_the_colour_stays(self):
        reduced = css()[css().rindex('@media (prefers-reduced-motion: reduce) { .stage-figure'):]
        self.assertIn('.stage-text .w1, .stage-text .w2 { animation: none; }', reduced)
        self.assertNotIn('--blood', reduced)

    def test_the_sign_in_page_still_has_the_words(self):
        page = Client().get('/accounts/login/').content.decode()
        self.assertIn('<span class="w1">RED</span><span class="w2">QUEEN</span>', page)

    def test_the_flat_banner_art_matches(self):
        banner = open(finders.find('web/banner.svg'), encoding='utf-8').read()
        self.assertEqual(len(re.findall(r'fill="#cf0f1f" filter="url\(#wordGlow\)">(RED|QUEEN)</text>', banner)), 2)
        self.assertIn('id="wordGlow"', banner)
