from django.urls import path
from . import views

app_name = 'collector'

urlpatterns = [
    # Members
    path('members/', views.assigned_members, name='members'),
    path('pending/', views.pending_members, name='pending'),

    # Collections
    path('add/', views.add_collection, name='add'),
    path('all-collections/', views.all_collections, name='all_collections'),
    path('request-admin-approval/<int:group_id>/', views.request_admin_approval, name='request_admin_approval'),

    path('collector/handover-pending/', views.HandoverPendingAPIView.as_view()),

    path('resend-payment/<int:payment_id>/', views.resend_payment, name='resend_payment'),
    path('resend-group/<int:group_id>/', views.resend_group_payments, name='resend_group_payments'),
    

    # Payment actions
    path('receipt/<int:payment_id>/', views.receipt, name='receipt'),
    path('edit/<int:payment_id>/', views.edit_payment, name='edit_payment'),
    path('delete/<int:payment_id>/', views.delete_payment, name='delete_payment'),

    # Member history
    path('history/<int:member_id>/', views.member_history, name='history'),

    # Reports
    path('reports/', views.reports, name='reports'),

    # Profile
    path('profile/', views.profile, name='profile'),

    # Logout
    path('logout/', views.logout_view, name='logout'),
]