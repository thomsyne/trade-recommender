from django.contrib import admin

from operations.models import JobOccurrence, ScheduledJob

admin.site.register(ScheduledJob)
admin.site.register(JobOccurrence)
