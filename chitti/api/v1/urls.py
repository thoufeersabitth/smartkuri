from django.urls import path
from chitti.api.v1.views import (
    # ===== Groups / Admin =====
    AddAuctionAPIView,
    AdminGroupCreateAPIView,
    AssignWinnerAPIView,
    AuctionDetailAPIView,
    AuctionListAPIView,
    AuctionListGroupAPIView,
    AuctionSpinAPIView,
    GroupDetailAPIView,
    EditGroupAPIView,
    AdminGroupListAPIView,
    GroupAdminProfileAPIView,
    GroupAdminDashboardAPIView,

    # ===== Cash Collectors =====
    CashCollectorListAPIView,
    CashCollectorCreateAPIView,
    CashCollectorUpdateAPIView,
    CashCollectorDeleteAPIView,
)

app_name = "chitti"

urlpatterns = [
    # ================= Admin Dashboard =================
    path(
        "admin/dashboard/",
        GroupAdminDashboardAPIView.as_view(),
        name="group-admin-dashboard"
    ),

    # ================= Admin Profile =================
    path(
        "admin/profile/",
        GroupAdminProfileAPIView.as_view(),
        name="group-admin-profile"
    ),

    # ================= Groups =================
    path(
        "admin/groups/create/",
        AdminGroupCreateAPIView.as_view(),
        name="admin-group-create"
    ),
    path(
        "admin/groups/",
        AdminGroupListAPIView.as_view(),
        name="admin-group-list"
    ),
    path(
        "admin/groups/<int:group_id>/",
        GroupDetailAPIView.as_view(),
        name="admin-group-detail"
    ),
    path(
        "admin/groups/<int:group_id>/edit/",
        EditGroupAPIView.as_view(),
        name="admin-group-edit"
    ),

    # ================= Cash Collectors =================
    path(
        "admin/collectors/",
        CashCollectorListAPIView.as_view(),
        name="admin-collector-list"
    ),
    path(
        "admin/collectors/create/",
        CashCollectorCreateAPIView.as_view(),
        name="admin-collector-create"
    ),
    path(
        "admin/collectors/<int:pk>/update/",
        CashCollectorUpdateAPIView.as_view(),
        name="admin-collector-update"
    ),
    path(
        "admin/collectors/<int:pk>/delete/",
        CashCollectorDeleteAPIView.as_view(),
        name="admin-collector-delete"
    ),

    # ================= Auctions =================
    # List all auctions
    path(
        "admin/auctions/",
        AuctionListAPIView.as_view(),
        name="admin-auction-list"
    ),
    path(
        "admin/auctions/group/<int:group_id>/",
        AuctionListGroupAPIView.as_view(),
        name="admin-auction-list-group"
    ),

    # Create auction
    path(
        "admin/auctions/create/",
        AddAuctionAPIView.as_view(),
        name="admin-auction-create"
    ),

    # Spin auction (get eligible members)
    path(
        "admin/auctions/<int:auction_id>/spin/",
        AuctionSpinAPIView.as_view(),
        name="admin-auction-spin"
    ),

    # Assign winner (AJAX)
    path(
        "admin/auctions/<int:auction_id>/assign-winner/",
        AssignWinnerAPIView.as_view(),
        name="admin-auction-assign-winner"
    ),

    # Auction detail
    path(
        "admin/auctions/<int:auction_id>/",
        AuctionDetailAPIView.as_view(),
        name="admin-auction-detail"
    ),
]
