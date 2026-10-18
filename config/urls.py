from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("inventory/", include("inventory.urls")),
    path("transactions/", include("transactions.urls")),
    path("maintenance/", include("maintenance.urls")),
    path("", include("dashboard.urls")),
    path("reports/", include("reports.urls")),
]
