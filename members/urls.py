from django.urls import path

from accounts import views
from .views import (
    member_auction_list,
    member_dashboard,
    member_payment_history,
    member_profile,
    member_list,
    member_create,
    member_edit,
    member_delete,
    member_details,        # full details / statement
    group_admin_profile
)

app_name = "members"

urlpatterns = [
    # ---------------- Dashboards / Profiles ----------------
    path('dashboard/', member_dashboard, name='member_dashboard'),
    path('profile/', member_profile, name='member_profile'),
    path("payments/", member_payment_history, name="member_payment_history"),
    path('auctions/', member_auction_list, name='member_auction_list'),

    # ---------------- Group Admin Profile ----------------
    path('group-admin/profile/', group_admin_profile, name='group_admin_profile'),

    # ---------------- Group Admin: Member CRUD ----------------
    path('admin/list/', member_list, name='member_list'),
    path('admin/create/', member_create, name='member_create'),
    path('admin/edit/<int:pk>/', member_edit, name='member_edit'),
    path('admin/delete/<int:pk>/', member_delete, name='member_delete'),

    # ---------------- Group Admin: Member Details / Statement ----------------
    path('admin/details/<int:pk>/', member_details, name='member_details'),
]
