from django.urls import path
from members.api.v1.views import (
    MemberCreateAPIView,
    MemberDeleteAPIView,
    MemberDetailAPIView,
    MemberListAPIView,
    MemberUpdateAPIView,
    MemberDashboardAPIView,
    MemberProfileAPIView,
    MemberPaymentsAPIView,
    MemberAuctionsAPIView
)

urlpatterns = [
    # -----------------------------
    # grup admin
    # -----------------------------
    path("members/", MemberListAPIView.as_view(), name="member-list"),
    path("members/create/", MemberCreateAPIView.as_view(), name="member-create"),
    path("members/<int:pk>/", MemberDetailAPIView.as_view(), name="member-detail"),
    path("members/<int:pk>/update/", MemberUpdateAPIView.as_view(), name="member-update"),
    path("members/<int:pk>/delete/", MemberDeleteAPIView.as_view(), name="member-delete"),

    # -----------------------------
    # Member Dashboard / Profile / Payments / Auctions
    # -----------------------------
    path("members/dashboard/", MemberDashboardAPIView.as_view(), name="member-dashboard"),
    path("members/profile/", MemberProfileAPIView.as_view(), name="member-profile"),
    path("members/payments/", MemberPaymentsAPIView.as_view(), name="member-payments"),
    path("members/auctions/", MemberAuctionsAPIView.as_view(), name="member-auctions"),
]