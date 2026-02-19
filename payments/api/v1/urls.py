from django.urls import path

from payments.api.v1.views import GroupPaymentCreateAPI, GroupPaymentDeleteAPI, GroupPaymentEditAPI, GroupPaymentListAPI


urlpatterns = [
    path("group/payments/", GroupPaymentListAPI.as_view()),
    path("group/payments/create/", GroupPaymentCreateAPI.as_view()),
    path("group/payments/<int:pk>/edit/", GroupPaymentEditAPI.as_view()),
    path("group/payments/<int:pk>/delete/", GroupPaymentDeleteAPI.as_view()),
   
]
