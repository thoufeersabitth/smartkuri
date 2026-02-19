# accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'  # important for namespacing

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('group-admin/dashboard/', views.group_admin_dashboard, name='group_admin_dashboard'),
    path('change-password/', views.change_password, name='change_password'),
    path('logout/', views.logout_view, name='logout'),
    path('group-signup/', views.group_signup, name='group_signup'),
    path('verify-group-otp/', views.verify_group_otp, name='verify_group_otp'),
    path('payment-page/', views.payment_page, name='payment_page'),
    path('payment-success/', views.payment_success, name='payment_success'),
    path('create-group-after-payment/', views.create_group_after_payment, name='create_group_after_payment'),
    path('resend-group-otp/', views.resend_group_otp, name='resend_group_otp'),
    path('password-reset/', views.password_reset_request, name='password_reset'),
    path('password-reset-confirm/', views.password_reset_confirm, name='password_reset_verify'),
    path(
    'collector/dashboard/',
    views.collector_dashboard,
    name='collector_dashboard'
),

]
