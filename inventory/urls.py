from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("", views.InventoryListView.as_view(), name="list"),
    path("export/csv/", views.export_csv, name="export_csv"),
    path("new/", views.ToolCreateView.as_view(), name="create"),
    path("<int:pk>/", views.ToolDetailView.as_view(), name="detail"),
    path("<int:pk>/drawer/", views.ToolDrawerView.as_view(), name="drawer"),
    path("<int:pk>/edit/", views.ToolUpdateView.as_view(), name="update"),
    path("quick-edit/", views.QuickEditToolView.as_view(), name="quick_edit"),
    path("bulk/", views.ToolBulkActionView.as_view(), name="bulk"),
]
