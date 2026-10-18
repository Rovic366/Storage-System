from django.contrib import admin

from .models import MaintenanceLog, MaintenanceSchedule


@admin.register(MaintenanceSchedule)
class MaintenanceScheduleAdmin(admin.ModelAdmin):
    list_display = ("tool", "task_type", "interval_days", "last_done", "next_due")
    list_filter = ("task_type",)
    search_fields = ("tool__sku",)
    list_select_related = ("tool",)


@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ("date", "tool", "task_type", "performed_by", "cost")
    list_filter = ("task_type",)
    search_fields = ("tool__sku", "notes")
    date_hierarchy = "date"
    list_select_related = ("tool", "performed_by")
