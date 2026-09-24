from django.contrib import admin

from .models import FaceTemplate, Infraction, Penalty, Person


@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'age_range', 'gender', 'total_occurrences', 'uuid', 'created_at')
    list_filter = ('age_range', 'gender')
    search_fields = ('full_name', 'uuid')
    readonly_fields = ('uuid', 'total_occurrences', 'created_at')


admin.site.register(FaceTemplate)
admin.site.register(Infraction)
admin.site.register(Penalty)
