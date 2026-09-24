from django.conf import settings
from django.db import models

from registry.models import Infraction, Penalty, Person


class Intake(models.Model):
    """A photo or video submitted to the system."""

    class MediaType(models.TextChoices):
        PHOTO = 'photo'
        VIDEO = 'video'

    class Status(models.TextChoices):
        RECEIVED = 'received'
        NO_FACE = 'no_face'
        NO_MATCH = 'no_match'
        AMBIGUOUS = 'ambiguous'
        NO_RECORD = 'no_record'  # identified, nothing on file: no profile is created
        PROFILED = 'profiled'

    media = models.FileField(upload_to='intakes/')
    media_type = models.CharField(max_length=8, choices=MediaType.choices)
    precinct = models.CharField(max_length=64, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    engine = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    faces_detected = models.PositiveIntegerField(default=0)
    match_threshold = models.FloatField(null=True, blank=True, help_text='Cosine similarity needed to accept a match')
    annotated = models.FileField(upload_to='intakes/annotated/', blank=True, help_text='Media with face boxes drawn')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def threshold_pct(self):
        return round(self.match_threshold * 100, 1) if self.match_threshold is not None else None


class FaceMatch(models.Model):
    """One face found in an intake and what it was compared with."""

    class Status(models.TextChoices):
        MATCHED = 'matched'
        AMBIGUOUS = 'ambiguous'
        NO_MATCH = 'no_match'

    intake = models.ForeignKey(Intake, on_delete=models.CASCADE, related_name='faces')
    index = models.PositiveIntegerField(help_text='Number shown on the annotated image (1-based)')
    frame_index = models.PositiveIntegerField(default=0)
    box_x = models.IntegerField(null=True, blank=True)
    box_y = models.IntegerField(null=True, blank=True)
    box_w = models.IntegerField(null=True, blank=True)
    box_h = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.SET_NULL, related_name='face_matches',
                               help_text='Accepted identity')
    candidate = models.ForeignKey(Person, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
                                  help_text='Closest enrolled person, accepted or not')
    score = models.FloatField(null=True, blank=True)
    runner_up_score = models.FloatField(null=True, blank=True)
    support = models.PositiveIntegerField(default=1, help_text='Frames the identity was seen in (video)')
    candidates = models.JSONField(default=list, help_text='Closest enrolled people: [{person_id, name, score}]')

    class Meta:
        ordering = ['intake_id', 'index']
        constraints = [models.UniqueConstraint(fields=['intake', 'index'], name='one_face_number_per_intake')]

    @staticmethod
    def pct(score):
        return None if score is None else round(max(score, 0) * 100, 1)

    @property
    def similarity_pct(self):
        return self.pct(self.score)

    @property
    def runner_up_pct(self):
        return self.pct(self.runner_up_score)

    @property
    def box(self):
        return None if self.box_x is None else (self.box_x, self.box_y, self.box_w, self.box_h)


class SuspectProfile(models.Model):
    class Status(models.TextChoices):
        VALIDATED = 'validated'
        NEEDS_REVIEW = 'needs_review'
        REJECTED = 'rejected'
        ADJUDICATED = 'adjudicated'

    intake = models.ForeignKey(Intake, null=True, blank=True, on_delete=models.SET_NULL, related_name='profiles')
    face_match = models.OneToOneField(FaceMatch, null=True, blank=True, on_delete=models.SET_NULL, related_name='profile')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='profiles')
    status = models.CharField(max_length=16, choices=Status.choices)
    snapshot = models.JSONField(help_text='Record summary at the time the profile was built')
    checks = models.JSONField(help_text='Automated validation checks and their results')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    review_notes = models.TextField(blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['intake', 'person'], name='one_profile_per_person_per_intake')]


class Judgment(models.Model):
    """Outcome applied to one open infraction: an (optional) conviction and/or a sentence."""

    profile = models.ForeignKey(SuspectProfile, on_delete=models.CASCADE, related_name='judgments')
    infraction = models.OneToOneField(Infraction, on_delete=models.CASCADE, related_name='judgment')
    convicted = models.BooleanField(default=False)
    sentence_kind = models.CharField(max_length=32, choices=Penalty.Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours = models.PositiveIntegerField(null=True, blank=True)
    months = models.PositiveIntegerField(null=True, blank=True)
    rationale = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    decided_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [
            ('review_profile', 'Can validate or reject suspect profiles'),
            ('adjudicate', 'Can apply convictions and sentences'),
        ]


class AuditEvent(models.Model):
    """Append-only trail of every identification, review and judgment."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    action = models.CharField(max_length=64)
    target = models.CharField(max_length=128)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
