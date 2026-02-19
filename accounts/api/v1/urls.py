# accounts/api/v1/urls.py
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from accounts.api.v1.views import (
    AddAdminAPIView,
    CreateGroupAfterPaymentAPIView,
    CreatePaymentOrderAPIView,
    GroupSignupAPIView,
    LoginAPIView,
    PaymentSuccessAPIView,
   
    ResendGroupOTPAPIView,
    LogoutAPIView,
    PasswordResetRequestAPIView,
    PasswordResetConfirmAPIView,
    FirstLoginChangePasswordAPIView,
    VerifyGroupOTPAPIView,
)

urlpatterns = [
    # JWT Auth
    path('login/', LoginAPIView.as_view(), name='api_login'),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Group Signup / Payment
    path('group/signup/', GroupSignupAPIView.as_view(), name='api_group_signup'),
    path('group/verify-otp/', VerifyGroupOTPAPIView.as_view(), name='api_group_verify_otp'),
    path('group/resend-otp/', ResendGroupOTPAPIView.as_view(), name='resend_group_otp'),
    path('group/payment-order/', CreatePaymentOrderAPIView.as_view(), name='api_group_payment_order'),
    path('group/payment-success/', PaymentSuccessAPIView.as_view(), name='api_group_payment_success'),
    path('group/create/', CreateGroupAfterPaymentAPIView.as_view(), name='api_create_group'),

    # Admin
    path('admin/add/', AddAdminAPIView.as_view(), name='api_add_admin'),

    # Logout
    path('logout/', LogoutAPIView.as_view(), name='api_logout'),

    # Password Reset
    path('password-reset/request/', PasswordResetRequestAPIView.as_view(), name='password_reset_request'),
    path('password-reset/confirm/', PasswordResetConfirmAPIView.as_view(), name='password_reset_confirm'),

    # First login change password
    path('first-login/change-password/', FirstLoginChangePasswordAPIView.as_view(), name='first_login_change_password'),
]
