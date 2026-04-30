from django.urls import path
from .views import (
    AddCollectionAPIView,
    CollectorDashboardAPIView,
    CollectorProfileAPIView,
    ListMembersAPIView,
    MemberHistoryAPIView,
    PendingMembersAPIView,
    ResendGroupPaymentsAPIView,
    ResendSinglePaymentAPIView,
    SendToAdminAPIView,
    TodayCollectionsAPIView,
    EditPaymentAPIView,    
    DeletePaymentAPIView, 
    CollectorReportsAPIView,
    AllCollectionsAPIView
)

urlpatterns = [
    path('collector/dashboard/', CollectorDashboardAPIView.as_view(), name='collector-dashboard'),
    path('collector/list-members/', ListMembersAPIView.as_view(), name='collector-list-members'),
    path("collector/members/<int:member_id>/history/", MemberHistoryAPIView.as_view(), name="member-history-api"),
    path("collector/add-collection/", AddCollectionAPIView.as_view(), name="api_add_collection"),
    path("collector/today-collections/", TodayCollectionsAPIView.as_view(), name="api_today_collections"),
    path("collector/pending-members/", PendingMembersAPIView.as_view(), name="collector-pending-members"),

    path('collector/collections/', AllCollectionsAPIView.as_view(), name='collector-all-collections'),

    # ------------------------------
    # Edit / Delete Payment APIs
    # ------------------------------
    path("collector/payments/<int:payment_id>/edit/", EditPaymentAPIView.as_view(), name="edit-payment"),
    path("collector/payments/<int:payment_id>/delete/", DeletePaymentAPIView.as_view(), name="delete-payment"),

    # ------------------------------
    # Send / Resend APIs
    # ------------------------------
    path('collector/collections/send-to-admin/', SendToAdminAPIView.as_view(), name='collector-send-to-admin'),
    path('collector/resend-payment/<int:payment_id>/', ResendSinglePaymentAPIView.as_view(), name='resend-single-payment'),
    path('collector/resend-group-payments/', ResendGroupPaymentsAPIView.as_view(), name='resend-group-payments'),

    # ------------------------------
    # Reports & Profile
    # ------------------------------
    path("collector/reports/", CollectorReportsAPIView.as_view(), name="collector-reports"),
    path("collector/profile/", CollectorProfileAPIView.as_view(), name="collector-profile"),
]