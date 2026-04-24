from django.urls import path

from payments.api.v1.views import (
    GroupPaymentCreateAPI,
    GroupPaymentDeleteAPI,
    GroupPaymentEditAPI,
    GroupPaymentListAPI,

    AdminPendingPaymentsAPI,
    GroupPaymentDetailsAPI,
    ApprovePaymentAPI,
    ApproveGroupPaymentsAPI,
    AdminNotificationAPI,
    RejectGroupPaymentsAPI,
    RejectPaymentAPI,
)

urlpatterns = [

    # =====================================================
    # 🔹 GROUP PAYMENTS (CRUD)
    # =====================================================
    path("group/payments/", GroupPaymentListAPI.as_view(), name="group-payment-list"),

    path("group/payments/create/", GroupPaymentCreateAPI.as_view(), name="group-payment-create"),

    path("group/payments/<int:pk>/edit/", GroupPaymentEditAPI.as_view(), name="group-payment-edit"),

    path("group/payments/<int:pk>/delete/", GroupPaymentDeleteAPI.as_view(), name="group-payment-delete"),


    # =====================================================
    # 🔹 ADMIN APPROVAL SYSTEM
    # =====================================================
    path("admin/pending-payments/", AdminPendingPaymentsAPI.as_view(), name="admin-pending-payments"),

    path("admin/pending-payments/", AdminPendingPaymentsAPI.as_view(), name="admin-pending-payments"),
    path("admin/group/<int:group_id>/payments/", GroupPaymentDetailsAPI.as_view(), name="group-payment-details"),
    path("admin/approve/payment/<int:payment_id>/", ApprovePaymentAPI.as_view(), name="approve-payment"),
    path("admin/reject/payment/<int:payment_id>/", RejectPaymentAPI.as_view(), name="reject-payment"),
    path("admin/approve/group/<int:group_id>/", ApproveGroupPaymentsAPI.as_view(), name="approve-group-payments"),
    path("admin/reject/group/<int:group_id>/", RejectGroupPaymentsAPI.as_view(), name="reject-group-payments"),
    path("admin/notifications/", AdminNotificationAPI.as_view(), name="admin-notifications"),

]