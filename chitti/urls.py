from django.urls import path
from . import views

app_name = 'chitti'

urlpatterns = [

    # -----------------------------
    # Group Management
    # -----------------------------
    path('groups/', views.group_management, name='group_management'),
    path('groups/add/', views.add_group, name='add_group'),
    path('groups/view/<int:group_id>/', views.view_group, name='view_group'),
    path('groups/edit/<int:group_id>/', views.edit_group, name='edit_group'),
    path('groups/close/<int:group_id>/', views.close_group, name='close_group'),
    path('groups/subscribe/<int:group_id>/', views.subscribe_group, name='subscribe_group'),

    # -----------------------------
    # Cash Collector Management
    # -----------------------------
    path('cash-collector/create/', views.create_cash_collector, name='create_cash_collector'),
    path('cash-collector/list/', views.cash_collector_list, name='cash_collector_list'),
    path('cash-collector/edit/<int:pk>/', views.edit_cash_collector, name='edit_cash_collector'),
    path('cash-collector/delete/<int:pk>/', views.delete_cash_collector, name='delete_cash_collector'),

    # -----------------------------
    # Subscription / Razorpay
    # -----------------------------
    path('groups/renew-subscription/<int:group_id>/', views.renew_subscription, name='renew_subscription'),
    path('razorpay/callback/', views.razorpay_callback, name='razorpay_callback'),

    # -----------------------------
    # Auction URLs
    # -----------------------------
    path('auction/', views.auction_list_view, name='auction_list'),
    path('auction/group/<int:group_id>/', views.auction_list_group_view, name='auction_list_group'),
    path('auction/add/', views.add_auction, name='add_auction'),
    path('auction/<int:auction_id>/', views.auction_detail_view, name='auction_detail'),
    path('auction/<int:auction_id>/spin/', views.auction_spin_view, name='auction_spin'),
    path('auction/<int:auction_id>/assign_winner_ajax/', views.assign_winner_ajax, name='assign_winner_ajax'),
    path('groups/edit-dates/<int:group_id>/', views.edit_auction_dates, name='edit_auction_dates'),
    path('auction/<int:auction_id>/assign-all/', views.assign_all_winners_ajax, name='assign_all_winners_ajax'),

    # -----------------------------
    # Admin Payments
    # -----------------------------
    path('admin/payments/pending/', views.admin_pending_payments, name='admin_pending_payments'),
    path('admin/payments/approve/<int:payment_id>/', views.admin_approve_payment, name='admin_approve_payment'),
    path('admin/payments/approve/group/<int:group_id>/', views.admin_approve_payment_group, name='admin_approve_payment_group'),
    path('admin/payments/group/<int:group_id>/details/', views.group_payment_details, name='group_payment_details'),
    path('admin/payments/reject/<int:payment_id>/', views.admin_reject_payment, name='admin_reject_payment'),
    path('admin/payments/reject/group/<int:group_id>/', views.admin_reject_payment_group, name='admin_reject_payment_group'),



    # -----------------------------
    # Notifications
    # -----------------------------
    path('notifications/clear-all/', views.clear_all_notifications, name='clear_all_notifications'),
]