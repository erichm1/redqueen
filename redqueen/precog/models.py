from django.db import models

from registry.models import Person


class RiskAssessment(models.Model):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='risk_assessments')
    score = models.FloatField()
    level = models.CharField(max_length=16)
    trajectory = models.CharField(max_length=16)
    expected_severity = models.FloatField()
    votes = models.JSONField()
    minority_report = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
