from django.contrib import admin

from .models import FaceTemplate, Infraction, Penalty, Person

admin.site.register(Person)
admin.site.register(FaceTemplate)
admin.site.register(Infraction)
admin.site.register(Penalty)
