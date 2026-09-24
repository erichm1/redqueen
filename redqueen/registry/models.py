from django.db import models


class Person(models.Model):
    full_name = models.CharField(max_length=255)
    date_of_birth = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return self.full_name

    def has_conviction_or_fine(self):
        """Risk assessment only applies to people with a conviction or a fine on record."""
        return (
            self.infractions.filter(convicted=True).exists()
            or Penalty.objects.filter(infraction__person=self, kind=Penalty.Kind.FINE).exists()
        )


class FaceTemplate(models.Model):
    """Reference face embedding. Embeddings from different engines are not comparable."""

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='templates')
    engine = models.CharField(max_length=64)
    embedding = models.JSONField()
    source = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.person} [{self.engine}]'


class Infraction(models.Model):
    class Category(models.TextChoices):
        TRAFFIC = 'traffic'
        VANDALISM = 'vandalism'
        THEFT = 'theft'
        FRAUD = 'fraud'
        DRUGS = 'drugs'
        BURGLARY = 'burglary'
        ASSAULT = 'assault'
        ROBBERY = 'robbery'

    class Status(models.TextChoices):
        OPEN = 'open'
        CLOSED = 'closed'

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='infractions')
    category = models.CharField(max_length=32, choices=Category.choices)
    severity = models.PositiveSmallIntegerField(help_text='1 (minor) to 5 (grave)')
    description = models.TextField(blank=True)
    occurred_at = models.DateTimeField()
    precinct = models.CharField(max_length=64, blank=True)
    convicted = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ['occurred_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(severity__gte=1, severity__lte=5), name='infraction_severity_1_5'
            ),
        ]

    def __str__(self):
        return f'{self.person} - {self.category} ({self.occurred_at:%Y-%m-%d})'


class Penalty(models.Model):
    class Kind(models.TextChoices):
        WARNING = 'warning'
        FINE = 'fine'
        COMMUNITY_SERVICE = 'community_service'
        PROBATION = 'probation'
        IMPRISONMENT = 'imprisonment'

    class Status(models.TextChoices):
        PENDING = 'pending'
        COMPLETED = 'completed'
        DEFAULTED = 'defaulted'

    infraction = models.ForeignKey(Infraction, on_delete=models.CASCADE, related_name='penalties')
    kind = models.CharField(max_length=32, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    hours = models.PositiveIntegerField(null=True, blank=True)
    months = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    imposed_at = models.DateTimeField()
    judgment = models.ForeignKey(
        'cases.Judgment', null=True, blank=True, on_delete=models.SET_NULL, related_name='penalties'
    )

    class Meta:
        ordering = ['imposed_at']
        verbose_name_plural = 'penalties'

    def __str__(self):
        return f'{self.kind} for {self.infraction}'
