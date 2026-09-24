"""Forward-looking risk from a person's *record history only*.

Three independent "precogs" (named after the film's) each score the record and vote on a risk
level. The consensus is the mean; a precog that disagrees with the consensus level files a
"minority report" that is stored with the assessment so a reviewer can see the dissent.

Inputs are limited to infractions, convictions and penalties. Face embeddings, appearance,
age, and other personal attributes never enter the model. The output is an advisory estimate
to support a human reviewer, not a finding about the person.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from django.utils import timezone

from registry.models import Penalty

ADVISORY = (
    'Statistical estimate from record history only. It is advisory, not evidence, '
    'and must not by itself justify any action against a person.'
)
HALF_LIFE_DAYS = 365.0
LOW_BELOW, HIGH_FROM = 0.33, 0.66


@dataclass
class Vote:
    precog: str
    score: float
    level: str
    trend: int  # +1 rising, 0 flat, -1 falling
    rationale: str


@dataclass
class RiskResult:
    score: float
    level: str
    trajectory: str  # more_severe | similar | less_severe
    expected_severity: float
    votes: list[Vote]
    minority_report: list[Vote] = field(default_factory=list)


def level_for(score: float) -> str:
    return 'low' if score < LOW_BELOW else 'high' if score >= HIGH_FROM else 'moderate'


def _age_days(when: datetime, now: datetime) -> float:
    return max((now - when).total_seconds() / 86400, 0.0)


def _decay(age_days: float) -> float:
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _vote(precog, score, trend, rationale) -> Vote:
    score = float(min(max(score, 0.0), 1.0))
    return Vote(precog, round(score, 3), level_for(score), trend, rationale)


def agatha(infractions, now) -> Vote:
    """How often, how recently and how seriously (severity-weighted) has this person offended?"""
    weight = sum(_decay(_age_days(i['occurred_at'], now)) * i['severity'] / 5 for i in infractions)
    last_year = sum(1 for i in infractions if _age_days(i['occurred_at'], now) <= 365)
    year_before = sum(1 for i in infractions if 365 < _age_days(i['occurred_at'], now) <= 730)
    trend = (last_year > year_before) - (last_year < year_before)
    score = 1 - math.exp(-weight)
    return _vote('agatha', score, trend,
                 f'{last_year} infraction(s) in the last 12 months vs {year_before} in the 12 before')


def arthur(infractions, now) -> Vote:
    """Are the offences getting more or less severe?"""
    ordered = sorted(infractions, key=lambda i: i['occurred_at'])
    severities = np.array([i['severity'] for i in ordered], dtype=float)
    weights = np.array([_decay(_age_days(i['occurred_at'], now)) for i in ordered])
    weighted_mean = float((severities * weights).sum() / weights.sum()) if weights.sum() else 0.0
    slope = float(np.polyfit(np.arange(len(severities)), severities, 1)[0]) if len(severities) >= 2 else 0.0
    trend = 1 if slope > 0.25 else -1 if slope < -0.25 else 0
    score = weighted_mean / 5 + 0.15 * trend
    return _vote('arthur', score, trend,
                 f'recency-weighted severity {weighted_mean:.1f}/5, slope {slope:+.2f} per infraction')


def dashiell(infractions, penalties, now) -> Vote:
    """Does the person comply with sanctions, and do they reoffend after them?"""
    ordered = sorted(infractions, key=lambda i: i['occurred_at'])
    defaulted = sum(1 for p in penalties if p['status'] == 'defaulted')
    defaulted_share = defaulted / len(penalties) if penalties else 0.0

    first_sanction = min(
        [p['imposed_at'] for p in penalties] + [i['occurred_at'] for i in ordered if i['convicted']],
        default=None,
    )
    after = [i for i in ordered if first_sanction and i['occurred_at'] > first_sanction]
    reoffend_share = len(after) / len(ordered) if ordered else 0.0

    since_last = _age_days(ordered[-1]['occurred_at'], now)
    recency = 0.5 ** (since_last / 730)
    score = 0.4 * defaulted_share + 0.35 * reoffend_share + 0.25 * recency
    trend = 1 if reoffend_share and recency > 0.5 else -1 if since_last > 730 else 0
    return _vote('dashiell', score, trend,
                 f'{defaulted} defaulted penalt(ies), {len(after)} offence(s) after first sanction, '
                 f'{since_last:.0f} days since last offence')


def assess_records(infractions, penalties, now=None) -> RiskResult | None:
    """infractions: [{occurred_at, severity, convicted}], penalties: [{kind, status, imposed_at}]."""
    if not infractions:
        return None
    now = now or timezone.now()
    votes = [agatha(infractions, now), arthur(infractions, now), dashiell(infractions, penalties, now)]
    score = round(sum(v.score for v in votes) / len(votes), 3)
    level = level_for(score)

    severity_vote = votes[1]
    ordered = sorted(infractions, key=lambda i: i['occurred_at'])
    expected = ordered[-1]['severity'] + (0.5 * severity_vote.trend if len(ordered) > 1 else 0)
    trajectory = {1: 'more_severe', 0: 'similar', -1: 'less_severe'}[severity_vote.trend]
    return RiskResult(
        score=score,
        level=level,
        trajectory=trajectory,
        expected_severity=round(min(max(expected, 1), 5), 2),
        votes=votes,
        minority_report=[v for v in votes if v.level != level],
    )


def assess_person(person, persist=True, now=None):
    """Assess a person. None if they have no conviction or fine on record; otherwise a stored
    RiskAssessment, or (persist=False) the bare RiskResult."""
    from .models import RiskAssessment

    if not person.has_conviction_or_fine():
        return None
    infractions = [
        {'occurred_at': i.occurred_at, 'severity': i.severity, 'convicted': i.convicted}
        for i in person.infractions.all()
    ]
    penalties = [
        {'kind': p.kind, 'status': p.status, 'imposed_at': p.imposed_at}
        for p in Penalty.objects.filter(infraction__person=person)
    ]
    result = assess_records(infractions, penalties, now)
    if not persist:
        return result
    return RiskAssessment.objects.create(
        person=person,
        score=result.score,
        level=result.level,
        trajectory=result.trajectory,
        expected_severity=result.expected_severity,
        votes=[vars(v) for v in result.votes],
        minority_report=[vars(v) for v in result.minority_report] or None,
    )
