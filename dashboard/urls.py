from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="index"),
    path("partials/grid/", views.dashboard_fragment, name="grid"),
    path("partials/feed/", views.dashboard_feed, name="feed"),
    path("api/dashboard/", views.api_dashboard, name="api_dashboard"),
    path("api/widget/<str:slug>/", views.api_widget, name="api_widget"),
    path("api/search/", views.api_search, name="api_search"),
]
