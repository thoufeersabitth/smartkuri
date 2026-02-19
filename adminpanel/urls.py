from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('group-admins/', views.group_admin_list, name='group_admin_list'),
    path('group-admin/block/<int:admin_id>/', views.block_group_admin, name='block_group_admin'),
    path('group-admin/unblock/<int:admin_id>/', views.unblock_group_admin, name='unblock_group_admin'),
    path('group-admin/renew/<int:admin_id>/', views.renew_subscription, name='renew_subscription'),
    path('subscriptions/', views.subscription_reports, name='subscription_reports'),
    path('reports/', views.reports, name='reports'),
    path('notifications/', views.send_notification, name='send_notification'),
    path('group-admin/<int:admin_id>/', views.group_admin_detail, name='group_admin_detail'),
]
