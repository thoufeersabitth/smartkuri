from django.urls import path
from . import views

app_name = 'collector'

urlpatterns = [
    # Members
    path('members/', views.assigned_members, name='members'),
    path('pending/', views.pending_members, name='pending'),

    # Collections
    path('add/', views.add_collection, name='add'),
    path('today/', views.today_collections, name='today'),

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
