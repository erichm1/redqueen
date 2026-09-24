"""COMPSTAT-style reporting, following its four principles:

1. Accurate, timely intelligence  -> counts, deltas and hot spots per precinct / category
2. Effective tactics              -> focus recommendations for each hot spot
3. Rapid deployment               -> resource split across precincts by weighted incident load
4. Relentless follow-up           -> unresolved cases and the current high-risk watchlist
"""
from collections import Counter
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone

from registry.models import Infraction, Penalty

from .models import RiskAssessment

UNASSIGNED = 'unassigned'


def _window(start, end):
    return Infraction.objects.filter(occurred_at__gte=start, occurred_at__lt=end)


def _pct_change(current, previous):
    if previous == 0:
        return None if current == 0 else 100.0
    return round((current - previous) / previous * 100, 1)


def report(days=28, now=None, hotspot_count=3):
    now = now or timezone.now()
    start, prev_start = now - timedelta(days=days), now - timedelta(days=2 * days)
    current, previous = _window(start, now), _window(prev_start, start)

    def by_precinct(qs):
        return {
            (row['precinct'] or UNASSIGNED): row
            for row in qs.values('precinct').annotate(n=Count('id'), load=Sum('severity'))
        }

    cur, prev = by_precinct(current), by_precinct(previous)
    precincts = []
    for name in sorted(set(cur) | set(prev)):
        n, before = cur.get(name, {}).get('n', 0), prev.get(name, {}).get('n', 0)
        precincts.append({
            'precinct': name, 'incidents': n, 'previous': before,
            'change_pct': _pct_change(n, before), 'severity_load': cur.get(name, {}).get('load', 0),
        })
    precincts.sort(key=lambda p: (p['severity_load'], p['incidents']), reverse=True)

    categories = Counter(current.values_list('category', flat=True))
    total, total_prev = current.count(), previous.count()

    # 2. tactics: the hottest precincts and what is driving them
    hotspots = []
    for p in precincts[:hotspot_count]:
        if not p['incidents']:
            continue
        precinct_filter = '' if p['precinct'] == UNASSIGNED else p['precinct']
        drivers = Counter(current.filter(precinct=precinct_filter).values_list('category', flat=True))
        top, count = drivers.most_common(1)[0]
        rising = p['change_pct'] is not None and p['change_pct'] > 0
        hotspots.append({
            'precinct': p['precinct'],
            'top_category': top,
            'recommendation': f'Focus on {top} ({count} of {p["incidents"]} incidents)'
                              f'{"; trend is rising" if rising else ""}',
        })

    # 3. deployment: proportional to severity-weighted load
    total_load = sum(p['severity_load'] for p in precincts) or 1
    deployment = [
        {'precinct': p['precinct'], 'share_pct': round(p['severity_load'] / total_load * 100, 1)}
        for p in precincts if p['severity_load']
    ]

    # 4. follow-up
    latest = {}
    for assessment in RiskAssessment.objects.select_related('person').order_by('created_at', 'id'):
        latest[assessment.person_id] = assessment
    watchlist = sorted(
        (a for a in latest.values() if a.level == 'high'), key=lambda a: a.score, reverse=True
    )
    follow_up = {
        'open_infractions': Infraction.objects.filter(status=Infraction.Status.OPEN).count(),
        'open_older_than_30_days': Infraction.objects.filter(
            status=Infraction.Status.OPEN, occurred_at__lt=now - timedelta(days=30)).count(),
        'pending_penalties': Penalty.objects.filter(status=Penalty.Status.PENDING).count(),
        'defaulted_penalties': Penalty.objects.filter(status=Penalty.Status.DEFAULTED).count(),
        'high_risk_watchlist': [
            {'person_id': a.person_id, 'name': a.person.full_name, 'score': a.score,
             'trajectory': a.trajectory}
            for a in watchlist
        ],
    }

    return {
        'period': {'start': start, 'end': now, 'days': days},
        'intelligence': {
            'total': total, 'previous_total': total_prev, 'change_pct': _pct_change(total, total_prev),
            'by_category': dict(categories.most_common()), 'by_precinct': precincts,
        },
        'tactics': hotspots,
        'deployment': deployment,
        'follow_up': follow_up,
    }
