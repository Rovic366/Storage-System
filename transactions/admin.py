from django.contrib import admin
from django.utils import timezone

from .models import Checkout, StockMovement


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "type", "tool", "quantity", "from_location", "to_location",
                    "performed_by", "reference_no")
    list_filter = ("type", "tool__location__warehouse")
    search_fields = ("tool__sku", "reference_no", "notes")
    date_hierarchy = "timestamp"
    list_select_related = ("tool", "from_location", "to_location", "performed_by")
    list_per_page = 100
    readonly_fields = ("timestamp",)


@admin.register(Checkout)
class CheckoutAdmin(admin.ModelAdmin):
    list_display = ("tool", "borrower", "status", "checked_out_at", "due_at",
                    "returned_at", "issued_by")
    list_filter = ("status",)
    search_fields = ("tool__sku", "borrower__username", "issued_by__username")
    date_hierarchy = "checked_out_at"
    list_select_related = ("tool", "borrower", "issued_by")
    list_per_page = 100
    actions = ["mark_overdue"]

    @admin.action(description="Mark selected open checkouts as overdue")
    def mark_overdue(self, request, queryset):
        updated = queryset.open().filter(due_at__lt=timezone.now()).update(
            status=Checkout.Status.OVERDUE
        )
        self.message_user(request, f"{updated} checkout(s) marked overdue.")
