from django.contrib import admin
from django.db.models import F, Sum

from .models import Category, Location, Supplier, Tool


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "tool_count")
    list_filter = ("parent",)
    search_fields = ("name",)
    ordering = ("parent__name", "name")

    @admin.display(description="Tools")
    def tool_count(self, obj):
        return obj.tools.count()


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_person", "email", "phone", "lead_time_days")
    search_fields = ("name", "contact_person", "email")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "warehouse", "zone", "rack", "shelf", "bin", "capacity", "occupancy")
    list_filter = ("warehouse", "zone", "is_active")
    search_fields = ("code", "warehouse")
    list_per_page = 100

    @admin.display(description="Occupied units")
    def occupancy(self, obj):
        total = obj.tools.aggregate(u=Sum("quantity_on_hand"))["u"] or 0
        return f"{total} / {obj.capacity}"


@admin.register(Tool)
class ToolAdmin(admin.ModelAdmin):
    list_display = (
        "sku", "name", "category", "location", "warehouse", "quantity_on_hand",
        "reorder_level", "status", "condition", "requires_calibration", "updated_at",
    )
    list_filter = ("status", "condition", "category", "location__warehouse", "supplier")
    search_fields = ("sku", "name", "manufacturer", "model_number", "serial_number", "barcode_value")
    ordering = ("sku",)
    list_select_related = ("category", "location")
    list_per_page = 100
    actions = ["retire_tools"]

    @admin.display(description="Warehouse", ordering="location__warehouse")
    def warehouse(self, obj):
        return obj.location.warehouse

    @admin.action(description="Retire selected tools")
    def retire_tools(self, request, queryset):
        for tool in queryset.exclude(status=Tool.Status.RETIRED):
            tool.status = Tool.Status.RETIRED
            tool.save(update_fields=["status", "updated_at"])
        self.message_user(request, f"{queryset.count()} tool(s) retired.")
