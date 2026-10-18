from django.urls import path

from . import views

app_name = "maintenance"

urlpatterns = [
    path("", views.ScheduleListView.as_view(), name="schedule"),
    path("<int:pk>/log/", views.LogTaskView.as_view(), name="log_task"),
    path("new/", views.ScheduleCreateView.as_view(), name="create"),
]
