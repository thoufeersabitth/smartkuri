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
    
# Auction URLs
    path('auction/', views.auction_list_view, name='auction_list'),
    # Auction list for a single group
path('auction/group/<int:group_id>/', views.auction_list_group_view, name='auction_list_group'),
           
    path('auction/add/', views.add_auction, name='add_auction'),        
    path('auction/<int:auction_id>/', views.auction_detail_view, name='auction_detail'),  # Detail page
    path('auction/<int:auction_id>/spin/', views.auction_spin_view, name='auction_spin'),  # Spin page
    path('auction/<int:auction_id>/assign_winner_ajax/', views.assign_winner_ajax, name='assign_winner_ajax'),  # AJAX winner

    

]
