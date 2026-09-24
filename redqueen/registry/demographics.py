"""Descriptive demographic buckets carried over from the precog project's Person entity.

These are for description and aggregate reporting only. They are never an input to the risk
model (precog.risk takes infractions and penalties, nothing else).
"""
from datetime import date

AGE_RANGES = [
    ('0-17', '0-17'),
    ('18-25', '18-25'),
    ('26-40', '26-40'),
    ('41-60', '41-60'),
    ('60+', '60+'),
]


def age_range_for(date_of_birth, today=None) -> str:
    """Bucket for a date of birth; '' when unknown or in the future."""
    if not date_of_birth:
        return ''
    today = today or date.today()
    years = today.year - date_of_birth.year - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    if years < 0:
        return ''
    for upper, label in ((17, '0-17'), (25, '18-25'), (40, '26-40'), (60, '41-60')):
        if years <= upper:
            return label
    return '60+'
