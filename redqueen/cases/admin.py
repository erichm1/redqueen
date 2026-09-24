from django.contrib import admin

from .models import AuditEvent, FaceMatch, Intake, Judgment, SuspectProfile

admin.site.register(Intake)
admin.site.register(FaceMatch)
admin.site.register(SuspectProfile)
admin.site.register(Judgment)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target')

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
