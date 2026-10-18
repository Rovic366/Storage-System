from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.ReportIndexView.as_view(), name="index"),
    path("<str:slug>/", views.ReportTableView.as_view(), name="table"),
    path("export/<str:filename>", views.ReportExportView.as_view(), name="export"),
]
