"""Dummy record scenarios shared by the seed command and the webcam enrolment page."""
import random
from datetime import timedelta

from django.utils import timezone

from .models import Infraction, Penalty

C, K, S = Infraction.Category, Penalty.Kind, Penalty.Status
PRECINCTS = ['P-01 Harbor', 'P-02 Midtown', 'P-03 Old Town', 'P-04 Riverside']

# key: (label, [(days_ago, category, severity, convicted, closed, penalty)])
# penalty: (kind, amount, hours, months, status) or None
SCENARIOS = {
    'clean': ('Clean record: identified, but no profile is built', []),
    'minor': ('Minor traffic matters: fine on record, low risk', [
        (400, C.TRAFFIC, 1, False, True, (K.FINE, 120, None, None, S.COMPLETED)),
        (30, C.TRAFFIC, 1, False, False, None),
    ]),
    'escalating': ('Escalating: petty theft, burglary, assault, open robbery', [
        (1100, C.THEFT, 2, False, True, (K.FINE, 300, None, None, S.COMPLETED)),
        (640, C.BURGLARY, 3, True, True, (K.COMMUNITY_SERVICE, None, 80, None, S.COMPLETED)),
        (200, C.ASSAULT, 4, True, True, (K.PROBATION, None, None, 12, S.PENDING)),
        (20, C.ROBBERY, 4, False, False, None),
    ]),
    'desisting': ('De-escalating: serious offences long ago, minor open matter now', [
        (1500, C.ROBBERY, 4, True, True, (K.IMPRISONMENT, None, None, 18, S.COMPLETED)),
        (1000, C.THEFT, 2, True, True, (K.FINE, 250, None, None, S.COMPLETED)),
        (300, C.TRAFFIC, 1, False, True, (K.FINE, 90, None, None, S.DEFAULTED)),
        (15, C.TRAFFIC, 1, False, False, None),
    ]),
}


def create_records(person, scenario, now=None):
    now = now or timezone.now()
    for days_ago, category, severity, convicted, closed, penalty in SCENARIOS[scenario][1]:
        when = now - timedelta(days=days_ago)
        infraction = Infraction.objects.create(
            person=person, category=category, severity=severity, occurred_at=when,
            precinct=random.Random(person.full_name + str(days_ago)).choice(PRECINCTS),
            convicted=convicted, status=Infraction.Status.CLOSED if closed else Infraction.Status.OPEN,
            description=f'Dummy {category} record',
        )
        if penalty:
            kind, amount, hours, months, status = penalty
            Penalty.objects.create(infraction=infraction, kind=kind, amount=amount, hours=hours, months=months,
                                   status=status, imposed_at=when + timedelta(days=30))
