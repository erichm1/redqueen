"""SVG ornaments for the hellgate on the sign-in portal: glowing cracks and a ring of runes on the stone ring.
Drawn in a viewBox centred on (0, 0); the ring is r = 262 (52 wide). Deterministic, so the gate is the same on every load."""
import math
import random

RING = 262


def _pts(points):
    return ' '.join(f'{x:.1f},{y:.1f}' for x, y in points)


def cracks_and_runes(rnd):
    parts = ['<g class="gate-cracks">']
    for _ in range(11):
        a = rnd.uniform(0, math.tau)
        r = RING + rnd.uniform(-16, 16)
        pts = []
        for _ in range(6):
            pts.append((r * math.cos(a), r * math.sin(a)))
            a += rnd.uniform(0.02, 0.05)
            r += rnd.uniform(-9, 9)
        parts.append('<polyline points="' + _pts(pts) + '"/>')
    parts.append('</g><g class="gate-runes">')
    glyphs = ('M0 -12V12M0 -12L8 -4M0 2L-8 -6', 'M0 -12V12M-7 -6L7 6', 'M0 -12V12M0 -12L8 -6L0 0M0 2L8 8', 'M-6 -12L6 12M6 -12L-6 12',
              'M0 -12V12M-7 -3H7', 'M-6 -12L0 -2L6 -12M0 -2V12')
    for i in range(40):
        parts.append(f'<path transform="rotate({360 * i / 40:.1f}) translate(0 -{RING})" d="{rnd.choice(glyphs)}"/>')
    parts.append('</g>')
    return ''.join(parts)


def gate_ornaments():
    return cracks_and_runes(random.Random(666))
