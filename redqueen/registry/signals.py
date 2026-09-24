from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Infraction, Person


def _refresh(person_id):
    person = Person.objects.filter(pk=person_id).first()
    if person:  # gone when the whole person is being deleted
        person.refresh_total_occurrences()


@receiver(post_save, sender=Infraction)
def infraction_saved(sender, instance, created, **kwargs):
    if created:
        _refresh(instance.person_id)


@receiver(post_delete, sender=Infraction)
def infraction_deleted(sender, instance, **kwargs):
    _refresh(instance.person_id)
