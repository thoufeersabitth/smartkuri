from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth import login as django_login
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.db import transaction
from rest_framework_simplejwt.tokens import RefreshToken
import random, time
import razorpay
from .serializers import *
from chitti.models import ChittiGroup, ChittiMember
from subscriptions.models import SubscriptionPlan, GroupSubscription
from payments.models import Payment
from members.models import Member
from accounts.models import StaffProfile
from django.conf import settings
import uuid
from rest_framework.decorators import api_view

User = get_user_model()

# ----------------------
# LOGIN API
# ----------------------
class LoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        identifier = serializer.validated_data['identifier']
        password = serializer.validated_data['password']

        user = authenticate(request, username=identifier, password=password)
        if not user:
            u = User.objects.filter(email=identifier).first()
            if u and u.check_password(password):
                user = u
        if not user:
            member = Member.objects.filter(phone=identifier).first()
            if member and member.user and member.user.check_password(password):
                user = member.user
        if not user:
            staff = StaffProfile.objects.filter(phone=identifier).first()
            if staff and staff.user.check_password(password):
                user = staff.user

        if user:
            refresh = RefreshToken.for_user(user)
            role = getattr(getattr(user, 'staffprofile', None), 'role', 'member')
            return Response({
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "username": user.username,
                "role": role
            })
        return Response({"detail":"Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)


# ----------------------
# GROUP SIGNUP API → session only
# ----------------------
class GroupSignupAPIView(APIView):
    permission_classes = []

    def post(self, request):
        serializer = GroupSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])
        otp = random.randint(100000, 999999)

        # Save signup info only in session
        request.session['pending_group_data'] = {
            'group_name': data['group_name'],
            'phone': data['phone'],
            'email': data['email'],
            'password': data['password1'],
            'plan_id': plan.id,
            'plan_price': float(plan.price),
            'otp': otp,
            'otp_created_at': time.time(),
            'otp_verified': False,
            'payment_done': False
        }

        # Send OTP email
        send_mail(
            f"SmartKuri - OTP for {data['group_name']}",
            f"Your OTP: {otp}",
            'no-reply@smartkuri.com',
            [data['email']],
            fail_silently=False
        )

        return Response({"detail": "OTP sent. Verify to proceed."}, status=200)

# ----------------------
# VERIFY OTP API → DB save here
# ----------------------
class VerifyGroupOTPAPIView(APIView):
    permission_classes = []

    def post(self, request):
        data = request.session.get('pending_group_data')
        if not data:
            return Response({"status": "error", "error": "No signup data found."}, status=400)

        otp_entered = request.data.get('otp')
        if not otp_entered:
            return Response({"status": "error", "error": "OTP is required."}, status=400)

        # OTP expiry check
        if time.time() - data.get('otp_created_at', 0) > 600:
            del request.session['pending_group_data']
            return Response({"status": "error", "error": "OTP expired. Please signup again."}, status=400)

        # OTP match check
        if str(otp_entered) != str(data.get('otp')):
            data['otp_attempts'] = data.get('otp_attempts', 0) + 1
            request.session['pending_group_data'] = data
            return Response({"status": "error", "error": "Invalid OTP."}, status=400)

        # ✅ OTP correct → DB save starts
        data['otp_verified'] = True
        User = get_user_model()

        # Create User after OTP verification
        owner = User.objects.create_user(
            username=data['email'],
            email=data['email'],
            password=data['password']
        )

        plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

        # Free plan → create group + staffprofile
        if plan.price <= 0 or getattr(plan, 'is_unlimited', False):
            group = ChittiGroup.objects.create(
                name=data['group_name'],
                owner=owner,
                total_amount=0.0,
                monthly_amount=0.0,
                duration_months=0,
                start_date=timezone.now().date()
            )

            StaffProfile.objects.create(
                user=owner,
                phone=data['phone'],
                role='group_admin',
                group=group,
                is_subscribed=False,
                subscription_end=None
            )

            data['payment_done'] = True
            request.session['pending_group_data'] = data

            return Response({
                "status": "success",
                "message": "OTP verified! Free plan activated. Group created.",
                "group_id": group.id,
                "group_name": group.name
            }, status=200)

        # Paid plan → proceed to payment page
        request.session['pending_group_data'] = data
        return Response({
            "status": "success",
            "message": "OTP verified! Proceed to payment.",
            "next_step": "payment_page"
        }, status=200)



# ----------------------
# PAYMENT ORDER API (Razorpay)
# ----------------------
class CreatePaymentOrderAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        data = request.session.get('pending_group_data')
        if not data or not data.get('otp_verified'):
            return Response({"detail":"Verify OTP first."}, status=400)

        plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])
        if plan.price <= 0 or getattr(plan, 'is_unlimited', False):
            data['payment_done'] = True
            request.session['pending_group_data'] = data
            return Response({"detail":"Free/unlimited plan. No payment needed."})

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        amount_paise = int(plan.price * 100)
        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"group_signup_{data['email']}",
            "payment_capture": 1
        })
        request.session['razorpay_order_id'] = order['id']
        return Response({"order_id": order['id'], "amount": amount_paise, "currency":"INR"})


# ----------------------
# PAYMENT SUCCESS API
# ----------------------
class PaymentSuccessAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.session.get('pending_group_data')
        if not data or not data.get('otp_verified'):
            return Response({"detail":"Session expired"}, status=400)

        payment_id = request.data.get('razorpay_payment_id')
        order_id = request.data.get('razorpay_order_id')
        signature = request.data.get('razorpay_signature')

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature
            })
            data['payment_done'] = True
            request.session['pending_group_data'] = data
            return Response({"detail":"Payment verified"})
        except razorpay.errors.SignatureVerificationError:
            return Response({"detail":"Payment verification failed"}, status=400)

# ----------------------
# CREATE GROUP AFTER PAYMENT
# ----------------------
class CreateGroupAfterPaymentAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def post(self, request):
        data = request.session.get('pending_group_data')
        if not data or not data.get('payment_done'):
            return Response({"detail":"Payment not completed"}, status=400)

        plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

        # Create admin user
        username = f"group_{random.randint(1000,9999)}"
        admin_user = User.objects.create_user(
            username=username,
            email=data['email'],
            password=data['password'],
            first_name=data['group_name']
        )

        group = ChittiGroup.objects.create(
            name=data['group_name'],
            owner=admin_user,
            total_amount=plan.price,
            monthly_amount=round(plan.price / plan.duration_days * 30,2) if plan.price>0 else 0,
            duration_months=plan.duration_days // 30,
            start_date=timezone.now().date()
        )

        staff_profile = StaffProfile.objects.create(
            user=admin_user,
            group=group,
            phone=data['phone'],
            role='group_admin',
            is_subscribed=True
        )

        if plan.price > 0:
            Payment.objects.create(
                collected_by=staff_profile,
                amount=plan.price,
                payment_method='razorpay',
                payment_status='success',
                group=group,
                subscription_plan=plan,
                paid_date=timezone.now().date()
            )

        GroupSubscription.objects.create(
            group=group,
            plan=plan,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=plan.duration_days),
            is_active=True
        )

        del request.session['pending_group_data']

        refresh = RefreshToken.for_user(admin_user)
        return Response({
            "detail":f"Group '{group.name}' created successfully",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "username": admin_user.username,
            "role":"group_admin"
        })

# ----------------------
# ADD ADMIN API
# ----------------------
class AddAdminAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if not hasattr(request.user, 'staffprofile') or request.user.staffprofile.role != 'admin':
            return Response({"detail":"Unauthorized"}, status=403)

        serializer = AddAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if User.objects.filter(username=data['username']).exists():
            return Response({"detail":"Username exists"}, status=400)
        if User.objects.filter(email=data['email']).exists():
            return Response({"detail":"Email exists"}, status=400)
        if StaffProfile.objects.filter(phone=data['phone']).exists():
            return Response({"detail":"Phone exists"}, status=400)

        user = User.objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            is_staff=(data['role'] != 'member'),
            is_superuser=(data['role'] == 'admin')
        )
        StaffProfile.objects.create(
            user=user,
            phone=data['phone'],
            role=data['role']
        )
        return Response({"detail":f"{data['role']} created successfully"})
    


    # ---------------------------------------
# RESEND GROUP OTP
# ---------------------------------------
class ResendGroupOTPAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.session.get('pending_group_data')
        if not data:
            return Response({"detail": "No signup data found. Please signup again."}, status=status.HTTP_400_BAD_REQUEST)

        # Generate new OTP
        new_otp = random.randint(100000, 999999)
        data['otp'] = new_otp
        data['otp_created_at'] = time.time()
        request.session['pending_group_data'] = data

        send_mail(
            "SmartKuri - New Group OTP",
            f"Your new OTP for group '{data['group_name']}' signup is: {new_otp}",
            settings.DEFAULT_FROM_EMAIL,
            [data['email']],
            fail_silently=False
        )

        return Response({"detail": "New OTP sent! Check your email."})


# ---------------------------------------
# LOGOUT API
# ---------------------------------------
class LogoutAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response({"detail": "Logged out successfully."})


# ---------------------------------------
# PASSWORD RESET REQUEST
# ---------------------------------------
class PasswordResetRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        identifier = request.data.get("identifier")
        user = None

        # Try email
        try:
            user = User.objects.get(email=identifier)
        except User.DoesNotExist:
            pass

        # Try member phone
        if not user:
            try:
                member = Member.objects.get(phone=identifier)
                user = member.user
            except Member.DoesNotExist:
                pass

        # Try staff phone
        if not user:
            try:
                profile = StaffProfile.objects.get(phone=identifier)
                user = profile.user
            except StaffProfile.DoesNotExist:
                pass

        if not user:
            return Response({"detail": "No user found with this email or phone."}, status=status.HTTP_404_NOT_FOUND)

        # Create OTP
        otp = random.randint(100000, 999999)
        request.session['password_reset_user_id'] = user.id
        request.session['password_reset_otp'] = otp
        request.session['otp_created_at'] = time.time()

        send_mail(
            "SmartKuri - Password Reset OTP",
            f"Your OTP for password reset is: {otp}",
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )

        return Response({"detail": "OTP sent to your email."})


# ---------------------------------------
# PASSWORD RESET CONFIRM
# ---------------------------------------
class PasswordResetConfirmAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user_id = request.session.get('password_reset_user_id')
        if not user_id:
            return Response({"detail": "Session expired. Try again."}, status=status.HTTP_400_BAD_REQUEST)

        user = get_object_or_404(User, id=user_id)

        otp_entered = request.data.get("otp")
        password1 = request.data.get("password1")
        password2 = request.data.get("password2")

        otp_saved = request.session.get('password_reset_otp')
        otp_time = request.session.get('otp_created_at')

        if not otp_saved or (time.time() - otp_time) > 300:
            return Response({"detail": "OTP expired. Please try again."}, status=status.HTTP_400_BAD_REQUEST)

        if str(otp_entered) != str(otp_saved):
            return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)
        if password1 != password2:
            return Response({"detail": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(password1)
        user.save()

        # Clear session
        request.session.pop('password_reset_user_id', None)
        request.session.pop('password_reset_otp', None)
        request.session.pop('otp_created_at', None)

        return Response({"detail": "Password reset successful! You can now login."})


# ---------------------------------------
# FIRST LOGIN CHANGE PASSWORD
# ---------------------------------------
class FirstLoginChangePasswordAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        member = Member.objects.filter(user=request.user).first()
        if not member:
            return Response({"detail": "Member not found."}, status=status.HTTP_404_NOT_FOUND)

        if not member.is_first_login:
            return Response({"detail": "Password already changed."}, status=status.HTTP_400_BAD_REQUEST)

        new_password = request.data.get('new_password')
        confirm_password = request.data.get('confirm_password')

        if new_password != confirm_password:
            return Response({"detail": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        user.set_password(new_password)
        user.save()

        # Keep session
        from django.contrib.auth import update_session_auth_hash
        update_session_auth_hash(request, user)

        member.is_first_login = False
        member.save()

        return Response({"detail": "Password changed successfully."})
