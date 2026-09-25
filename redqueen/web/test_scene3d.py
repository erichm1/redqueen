"""Geometric checks on the 3D scene's constants (parsed from queen3d.js), so a change that makes the scepter cross her
legs, or puts the circle out of her arm's reach, fails here instead of being noticed on screen."""
import math
import re

import numpy as np
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase


def js():
    return open(finders.find('web/queen3d.js'), encoding='utf-8').read()


def floats(pattern, text, count):
    match = re.search(pattern, text)
    assert match, f'pattern not found in queen3d.js: {pattern}'
    return [float(match.group(i + 1)) for i in range(count)]


def segment_distance(p1, q1, p2, q2):
    """Smallest distance between segments p1-q1 and p2-q2 in 3D."""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2
    a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    c, b = d1 @ r, d1 @ d2
    denom = a * e - b * b
    s = np.clip((b * f - c * e) / denom, 0, 1) if denom > 1e-12 else 0.0
    t = (b * s + f) / e
    if t < 0:
        t, s = 0.0, np.clip(-c / a, 0, 1)
    elif t > 1:
        t, s = 1.0, np.clip((b - c) / a, 0, 1)
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * t)))


class SceneGeometryTests(SimpleTestCase):
    def setUp(self):
        text = js()
        self.cx, self.cz, self.radius, self.lap, self.hand_height, self.orbit = floats(
            r'const SWEEP = \{ cx: ([\d.]+), cz: ([\d.]+), radius: ([\d.]+), lap: ([\d.]+), handHeight: ([\d.]+), handOrbit: ([\d.]+) \}', text, 6)
        (self.lean,) = floats(r'const LEAN = ([\d.]+);', text, 1)
        (hip_x, hip_y) = floats(r'J\.hipL\.set\(L \* ([\d.]+), ([\d.]+) - dip, 0\)', text, 2)
        knee_l = floats(r'J\.kneeL\.set\(L \* \(([\d.]+) \+ [\d.]+ \* bob\), ([\d.]+) - dip \* 0\.4, ([\d.]+) \+', text, 3)
        knee_r = floats(r'J\.kneeR\.set\(R \* \(([\d.]+) \+ [\d.]+ \* bob\), ([\d.]+) - dip \* 0\.4, ([\d.]+) \+', text, 3)
        ankle_l = floats(r'J\.ankleL\.set\(L \* ([\d.]+), ([\d.]+), ([\d.]+)\)', text, 3)
        ankle_r = floats(r'J\.ankleR\.set\(R \* ([\d.]+), ([\d.]+), ([\d.]+)\)', text, 3)
        self.l1, self.l2 = floats(r'elbowFor\(J\.shL, J\.fiL, ([\d.]+), ([\d.]+),', text, 2)
        self.legs = {
            'left': [np.array([-hip_x, hip_y, 0.0]), np.array([-knee_l[0], knee_l[1], knee_l[2]]), np.array([-ankle_l[0], ankle_l[1], ankle_l[2]])],
            'right': [np.array([hip_x, hip_y, 0.0]), np.array([knee_r[0], knee_r[1], knee_r[2]]), np.array([ankle_r[0], ankle_r[1], ankle_r[2]])],
        }
        (self.staff_above_hand,) = floats(r'STAFF_ABOVE_HAND = ([\d.]+),', text, 1)

    def lap_positions(self, step_degrees=3):
        for degrees in range(0, 360, step_degrees):
            a = math.radians(degrees)
            tip = np.array([self.cx + self.radius * math.cos(a), 0.012, self.cz + self.radius * math.sin(a)])
            hand = np.array([self.cx + self.orbit * math.cos(a), self.hand_height, self.cz + self.orbit * math.sin(a)])
            yield degrees, tip, hand

    def test_the_scepter_never_comes_near_her_legs(self):
        leg_radius, staff_radius, margin = 0.11, 0.03, 0.04
        for degrees, tip, hand in self.lap_positions():
            top = hand + (hand - tip) / np.linalg.norm(hand - tip) * self.staff_above_hand
            for side, (hip, knee, ankle) in self.legs.items():
                for a, b in ((hip, knee), (knee, ankle)):
                    gap = segment_distance(tip, top, a, b)
                    self.assertGreater(gap, leg_radius + staff_radius + margin,
                                       f'the scepter is {gap:.2f} from her {side} leg at {degrees} degrees')

    def test_the_tip_stays_in_front_of_her_feet_never_between_them(self):
        feet = [self.legs['left'][2], self.legs['right'][2]]
        for degrees, tip, _ in self.lap_positions():
            in_front = tip[2] > max(f[2] for f in feet) + 0.08
            beside = tip[0] > max(f[0] for f in feet) + 0.12 or tip[0] < min(f[0] for f in feet) - 0.12
            self.assertTrue(in_front or beside, f'the tip is level with her feet, between or on them, at {degrees} degrees')
        self.assertGreater(self.cz - self.radius, self.legs['right'][2][2] + 0.08)   # the whole circle is ahead of the feet

    def test_the_arm_can_reach_the_scepter_grip_all_lap(self):
        reach = self.l1 + self.l2
        for lean in (self.lean - 0.03, self.lean + 0.03):
            for twist in (-0.1, 0.0, 0.1):
                rx = np.array([[1, 0, 0], [0, math.cos(lean), -math.sin(lean)], [0, math.sin(lean), math.cos(lean)]])
                ry = np.array([[math.cos(twist), 0, math.sin(twist)], [0, 1, 0], [-math.sin(twist), 0, math.cos(twist)]])
                shoulder = rx @ ry @ np.array([0.245, 1.3, 0.0]) + np.array([0, 0.85 - 0.85 * math.cos(lean), -0.85 * math.sin(lean)])
                for degrees, _, hand in self.lap_positions(6):
                    distance = float(np.linalg.norm(hand - shoulder))
                    self.assertLess(distance, reach - 0.02, f'shoulder to grip is {distance:.2f} (arm reach {reach:.2f}) at {degrees} degrees, lean {lean:.2f}, twist {twist}')


class SceneContentTests(SimpleTestCase):
    def test_the_circle_writes_rq_in_the_wordmark_font_on_the_scepters_clock(self):
        text = js()
        self.assertIn("fillText('R'", text)
        self.assertIn("fillText('Q'", text)
        font = re.search(r"const RUNE_FONT = '([^']+)", text).group(1)
        css = open(finders.find('web/style.css'), encoding='utf-8').read()
        body = re.search(r'body \{[^}]*font: ([^;]+);', css).group(1)
        wordmark = re.search(r'\.stage-text \.w1, \.stage-text \.w2 \{([^}]*)\}', css).group(1)
        self.assertIn('font-weight: 700', wordmark)
        self.assertTrue(font.startswith('700 '))
        for family in ('system-ui', '-apple-system', 'Segoe UI', 'Roboto'):     # the same stack the page (and wordmark) uses
            self.assertIn(family, font)
            self.assertIn(family, body.replace('"', ''))
        self.assertRegex(text, r'paintRunes\(\(\(\(t % SWEEP\.lap\)')                # progress comes from the same lap clock as the tip
        self.assertIn('0x8b0206', text.replace('#8b0206', '0x8b0206'))               # blood red
        (lap,) = floats(r'lap: ([\d.]+)', text, 1)
        fx = open(finders.find('web/queen-fx.css'), encoding='utf-8').read()
        for rule in ('q-circle', 'q-rq-r', 'q-rq-q', 'q-staff'):                    # the 2D fallback runs on the same clock
            self.assertRegex(fx, rf'animation: {rule} {lap:g}s')

    def test_the_wings_are_veined(self):
        text = js()
        for piece in ('function wingTextures', 'bumpMap: wingMaps.bump', 'emissiveMap: wingMaps.glow', 'branch(g, rnd', 'g.setAttribute(\'uv\''):
            self.assertIn(piece, text)

    def test_the_look_requested(self):
        text = js()
        self.assertIn('0x9fd2f0', text)                       # light blue skin
        self.assertIn("'#e01a22'", text)                       # solid red eyes
        self.assertRegex(text, r'wing\.scale\.set\(side \* 1\.12')  # bigger wings
        self.assertNotIn('jab', text.lower())                 # the punch is gone


class PrivacyEyesTests(SimpleTestCase):
    """While the password is typed she closes her eyes: the model, the page script and the 2D fallback all take part."""

    def test_the_model_has_eyelids_and_a_blink(self):
        text = js()
        for piece in ('localClippingEnabled = true', 'setEyesClosed(closed, immediate = false)', 'lidPlane', 'closedTarget',
                      'const blink = ', 'lashMaterial'):
            self.assertIn(piece, text)
        (blink_every,) = floats(r'blinkPhase = \(\(t % ([\d.]+)\)', text, 1)
        self.assertGreater(blink_every, 2.0)     # an occasional blink, not a twitch

    def test_the_page_closes_her_eyes_while_the_password_field_has_focus(self):
        script = open(finders.find('web/stage3d.js'), encoding='utf-8').read()
        self.assertIn("getElementById('id_password')", script)
        self.assertRegex(script, r"addEventListener\('focus', function \(\) \{ eyes\(true\); \}\)")
        self.assertRegex(script, r"addEventListener\('blur', function \(\) \{ eyes\(false\); \}\)")
        self.assertIn("classList.toggle('eyes-closed', closed)", script)
        self.assertIn('queen.setEyesClosed(closed, reduced)', script)          # reduced motion: no easing
        self.assertIn('document.activeElement === password', script)           # typing before the scene finished loading

    def test_the_sign_in_form_really_uses_that_field_id(self):
        from django.test import Client
        page = Client().get('/accounts/login/').content.decode()
        self.assertIn('name="password"', page)
        self.assertIn('id="id_password"', page)

    def test_the_2d_fallback_has_lids_that_close_on_the_same_signal(self):
        from django.template.loader import get_template
        stage = open(get_template('web/_queen_stage.html').origin.name, encoding='utf-8').read()
        self.assertEqual(stage.count('class="fx-lid"'), 2)
        css = open(finders.find('web/style.css'), encoding='utf-8').read()
        self.assertRegex(css, r'\.stage3d\.eyes-closed \.fx-lid \{ transform: scaleY\(1\); \}')
        fx = open(finders.find('web/queen-fx.css'), encoding='utf-8').read()
        self.assertRegex(fx, r'\.fx-lid \{[^}]*scaleY\(0\)')                    # open by default, also in the standalone SVGs
