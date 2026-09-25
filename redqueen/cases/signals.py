from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import AuditEvent, Intake


@receiver(post_delete, sender=Intake)
def intake_deleted(sender, instance, **kwargs):
    """Deleting an intake by any route (admin, cascade, code) removes its media from disk."""
    for field in (instance.media, instance.annotated):
        if field:
            field.delete(save=False)


def _ip(request):
    return request.META.get('REMOTE_ADDR') if request is not None else None


@receiver(user_logged_in)
def signed_in(sender, request, user, **kwargs):
    AuditEvent.objects.create(actor=user, action='user.login', target=f'user:{user.pk}', detail={'ip': _ip(request)})


@receiver(user_logged_out)
def signed_out(sender, request, user, **kwargs):
    if user is not None:
        AuditEvent.objects.create(actor=user, action='user.logout', target=f'user:{user.pk}', detail={'ip': _ip(request)})


@receiver(user_login_failed)
def sign_in_failed(sender, credentials, request=None, **kwargs):
    # the attempted username is recorded, never the password
    AuditEvent.objects.create(action='user.login_failed', target='user:?',
                              detail={'username': credentials.get('username', ''), 'ip': _ip(request)})
