from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    # Group Admin
    path('group/list/', views.group_payment_list, name='group_payment_list'),
    path('group/add/', views.group_payment_create, name='group_payment_create'),
    path('group/edit/<int:pk>/', views.group_payment_edit, name='group_payment_edit'),
    path('group/delete/<int:pk>/', views.group_payment_delete, name='group_payment_delete'),
    path('group/history/', views.group_cash_collected_history, name='group_cash_collected_history'),
]
