"""Sentencing recommendations.

ILLUSTRATIVE guideline table for the demo. Real guidelines are set by law, not by this table,
and a recommendation is never applied without a human decision (see services.apply_judgment).
"""
from dataclasses import asdict, dataclass

from registry.models import Infraction, Penalty


@dataclass
class Recommendation:
    infraction_id: int
    convicted: bool
    sentence_kind: str
    amount: int | None
    hours: int | None
    months: int | None
    rationale: str

    def as_dict(self):
        return asdict(self)


def recommend(infraction: Infraction) -> Recommendation:
    priors = (
        Infraction.objects.filter(person=infraction.person, occurred_at__lt=infraction.occurred_at)
        .exclude(pk=infraction.pk)
        .count()
    )
    prior_convictions = Infraction.objects.filter(
        person=infraction.person, convicted=True, occurred_at__lt=infraction.occurred_at
    ).count()
    severity = infraction.severity
    convicted = severity >= 4 or (severity == 3 and prior_convictions >= 1)

    kind, amount, hours, months = Penalty.Kind.WARNING, None, None, None
    if severity == 1:
        if priors:
            kind, amount = Penalty.Kind.FINE, 50 * (1 + priors)
    elif severity == 2:
        kind, amount = Penalty.Kind.FINE, 200 * (1 + priors)
    elif severity == 3:
        kind, hours = Penalty.Kind.COMMUNITY_SERVICE, 40 + 20 * priors
    elif severity == 4:
        kind, months = Penalty.Kind.PROBATION, 12 + 6 * prior_convictions
    else:
        kind, months = Penalty.Kind.IMPRISONMENT, 24 + 12 * prior_convictions

    rationale = (
        f'Severity {severity} {infraction.category}; {priors} prior infraction(s), '
        f'{prior_convictions} prior conviction(s).'
    )
    return Recommendation(infraction.pk, convicted, kind, amount, hours, months, rationale)
