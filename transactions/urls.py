from django.urls import path

from . import views

app_name = "transactions"

urlpatterns = [
    path("ops/", views.StockOpsView.as_view(), name="ops_default"),
    path("ops/<str:op>/", views.StockOpsView.as_view(), name="ops"),
    path("ops/<str:op>/submit/", views.StockOpSubmitView.as_view(), name="op_submit"),
    path("checkouts/", views.CheckoutListView.as_view(), name="checkout_list"),
    path("checkout/new/", views.CheckoutFastEntryView.as_view(), name="checkout_new"),
    path("checkout/<int:pk>/return/", views.ReturnCheckoutView.as_view(), name="checkout_return"),
]
