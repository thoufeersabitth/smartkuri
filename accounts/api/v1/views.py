from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import get_user_model, authenticate, update_session_auth_hash
from django.contrib.auth import login as django_login
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.authentication import JWTAuthentication
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
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser





# ----------------------
# LOGIN API
# ----------------------





User = get_user_model()

class LoginAPIView(APIView):
    permission_classes = []

    def post(self, request):
        identifier = request.data.get('identifier')
        password = request.data.get('password')

        # ✅ Validate input
        if not identifier or not password:
            return Response(
                {"error": "Identifier and password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = None

        # 1️⃣ Username login
        user = authenticate(request, username=identifier, password=password)

        # 2️⃣ Email login
        if user is None:
            u = User.objects.filter(email=identifier).first()
            if u and u.check_password(password):
                user = u

        # 3️⃣ Member phone login
        if user is None:
            member = Member.objects.filter(phone=identifier).first()
            if member and member.user and member.user.check_password(password):
                user = member.user

        # 4️⃣ Staff phone login
        if user is None:
            staff = StaffProfile.objects.filter(phone=identifier).first()
            if staff and staff.user and staff.user.check_password(password):
                user = staff.user

        # =====================================
        # ✅ FINAL RESPONSE
        # =====================================
        if user:

            # 🚫 Disabled account
            if not user.is_active:
                return Response(
                    {"error": "Your account is disabled"},
                    status=status.HTTP_403_FORBIDDEN
                )

            # 🔐 Generate JWT tokens
            refresh = RefreshToken.for_user(user)

            # Default values
            role = "member"
            redirect_to = "members:member_dashboard"
            group_setup_needed = False
            first_login = False

            # =====================================
            # 👨‍💼 STAFF LOGIC
            # =====================================
            if hasattr(user, 'staffprofile'):

                profile = user.staffprofile
                role = profile.role

                if role == 'admin':
                    redirect_to = "adminpanel:dashboard"

                elif role == 'collector':
                    redirect_to = "accounts:collector_dashboard"

                elif role == 'group_admin':

                    if not profile.group:
                        group_setup_needed = True
                        redirect_to = "accounts:create_group"

                    else:
                        redirect_to = "accounts:group_admin_dashboard"

            # =====================================
            # 👤 MEMBER LOGIC
            # =====================================
            elif hasattr(user, 'member_profile'):

                member = user.member_profile

                # ✅ ONLY CHECK
                if member.is_first_login:
                    first_login = True
                    redirect_to = "members:first_login_setup"

                else:
                    redirect_to = "members:member_dashboard"

            # =====================================
            # 🔄 MULTI-ROLE & PORTAL SWITCHING
            # =====================================
            has_admin_role = False
            has_collector_role = False
            kuris_list = []

            staff_prof = StaffProfile.objects.filter(user=user).first()
            if staff_prof:
                if staff_prof.role in ['group_admin', 'admin']:
                    has_admin_role = True
                    has_collector_role = True
                elif staff_prof.role == 'collector':
                    has_collector_role = True
                    for g in staff_prof.assigned_chitti_groups.filter(is_active=True):
                        kuris_list.append({'id': g.id, 'name': g.name, 'code': g.code})

            members = Member.objects.filter(
                Q(user=user) | Q(email=user.email) | Q(phone=user.username)
            )
            for m in members:
                if m.assigned_chitti_group and not any(k['id'] == m.assigned_chitti_group.id for k in kuris_list):
                    kuris_list.append({
                        'id': m.assigned_chitti_group.id,
                        'name': m.assigned_chitti_group.name,
                        'code': m.assigned_chitti_group.code
                    })
                for cm in m.chitti_memberships.all():
                    if not any(k['id'] == cm.group.id for k in kuris_list):
                        kuris_list.append({
                            'id': cm.group.id,
                            'name': cm.group.name,
                            'code': cm.group.code
                        })

            # =====================================
            # ✅ SUCCESS RESPONSE
            # =====================================
            return Response({
                "status": "success",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user_id": user.id,
                "email": user.email,
                "username": user.username,
                "role": role,
                "has_admin_role": has_admin_role,
                "has_collector_role": has_collector_role,
                "kuris": kuris_list,
                "redirect_to": redirect_to,
                "group_setup_needed": group_setup_needed,
                "first_login": first_login
            }, status=status.HTTP_200_OK)

        # ❌ Invalid login
        return Response(
            {"error": "Invalid login details"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

class SubscriptionPlanListAPIView(APIView):
    permission_classes = []

    def get(self, request):
        plans = SubscriptionPlan.objects.filter(is_active=True)
        serializer = SubscriptionPlanSerializer(plans, many=True)

        return Response({
            "success": True,
            "plans": serializer.data
        }, status=status.HTTP_200_OK)





User = get_user_model()

class GroupSignupAPIView(APIView):
    permission_classes = []

    def post(self, request):
        # 1. Get data using the EXACT keys from your Postman JSON
        email = request.data.get('email')
        phone = request.data.get('phone')
        password = request.data.get('password') # Changed from password1 to password
        name = request.data.get('name')

        # 2. Validation
        # If any of these are missing in the JSON, it returns this error
        if not email or not phone or not password or not name:
            return Response({"error": "All fields (name, email, phone, password) are required."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        if User.objects.filter(email=email).exists():
            return Response({"error": "Email already registered."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        # 3. Generate OTP
        otp = str(random.randint(100000, 999999))
        print(f"DEBUG OTP for {email}: {otp}") 

        # 4. Save to Session
        request.session['pending_group_data'] = {
            'name': name,
            'phone': phone,
            'email': email,
            'password': password, # Plain text for now, hashed in Verify view
            'otp': otp
        }
        request.session.modified = True 

        # 5. Send Email
        try:
            send_mail(
                "Verify Your Account",
                f"Your registration OTP is {otp}",
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False 
            )
            return Response({
                "message": "OTP sent successfully.",
                "email": email
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({"error": f"Mail error: {str(e)}"}, 
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# ----------------------
# VERIFY OTP API
# ----------------------


User = get_user_model()

class VerifyGroupOTPAPIView(APIView):
    permission_classes = []

    def post(self, request):
        # 1. Fetch data stored in session during Signup
        data = request.session.get('pending_group_data')
        entered_otp = request.data.get('otp')

        # Check if session exists
        if not data:
            return Response({"error": "Session expired or not found. Please signup again."}, 
                            status=status.HTTP_400_BAD_REQUEST)

        # 2. OTP Verification Logic
        if str(entered_otp) == str(data.get('otp')):
            try:
                with transaction.atomic():
                    email = data.get('email')
                    password = data.get('password')
                    phone = data.get('phone')
                    name = data.get('name')

                    # 3. Create or Update the User
                    user = User.objects.filter(email=email).first()
                    
                    if not user:
                        # ✅ Standard way to create user with hashed password
                        user = User.objects.create_user(
                            username=email, # We are using email as the username
                            email=email,
                            password=password
                        )
                        user.first_name = name
                        user.save()
                    else:
                        # If user exists, update password correctly
                        user.set_password(password)
                        user.save()

                    # 4. Link User to StaffProfile (Role: Group Admin)
                    StaffProfile.objects.update_or_create(
                        user=user,
                        defaults={
                            'phone': phone,
                            'role': 'group_admin',
                            'group': None,
                            'is_subscribed': False
                        }
                    )

                # 5. Success - Cleanup Session
                request.session.pop('pending_group_data', None)
                request.session.modified = True

                return Response({
                    "status": "success",
                    "message": "Signup successful! You can now login using your email."
                }, status=status.HTTP_201_CREATED)

            except Exception as e:
                return Response({"error": f"Database Error: {str(e)}"}, 
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        else:
            return Response({"error": "Invalid OTP. Please check your email again."}, 
                            status=status.HTTP_400_BAD_REQUEST)
        
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


# Helper to resolve user from identifier
def find_user_by_identifier(identifier):
    if not identifier:
        return None
    identifier = str(identifier).strip()
    user = User.objects.filter(email__iexact=identifier).first()
    if not user:
        user = User.objects.filter(username__iexact=identifier).first()
    if not user:
        mem = Member.objects.filter(phone=identifier).first()
        if mem and mem.user:
            user = mem.user
    if not user:
        staff = StaffProfile.objects.filter(phone=identifier).first()
        if staff and staff.user:
            user = staff.user
    return user


# ---------------------------------------
# PASSWORD RESET REQUEST
# ---------------------------------------
class PasswordResetRequestAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from accounts.views import send_professional_otp_email
        from django.core.cache import cache

        identifier = request.data.get("identifier") or request.data.get("email")
        if not identifier:
            return Response({"detail": "Email or Phone number is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = find_user_by_identifier(identifier)
        if not user:
            return Response({"detail": "No account found with this email or phone number."}, status=status.HTTP_404_NOT_FOUND)

        if not user.email:
            return Response({"detail": "No registered email associated with this account. Please contact admin."}, status=status.HTTP_400_BAD_REQUEST)

        otp = str(random.randint(100000, 999999))
        
        # Save to cache & session
        cache_key = f"pwd_reset_otp_{user.id}"
        cache.set(cache_key, otp, timeout=300)
        cache.set(f"pwd_reset_user_{user.id}", user.id, timeout=300)

        if hasattr(request, 'session'):
            request.session['password_reset_user_id'] = user.id
            request.session['password_reset_otp'] = otp
            request.session['otp_created_at'] = time.time()

        send_professional_otp_email(
            recipient_email=user.email,
            otp_code=otp,
            subject="🔑 Password Reset Verification - SmartKuri",
            title_text="Password Reset Request",
            body_text="We received a request to reset your SmartKuri account password. Use the single verification code below to set your new password across all portals.",
            target_name="Unified Single Password Reset"
        )

        return Response({
            "status": "success",
            "detail": f"OTP sent to {user.email}",
            "email": user.email,
            "user_id": user.id
        }, status=status.HTTP_200_OK)


# ---------------------------------------
# RESEND PASSWORD RESET OTP
# ---------------------------------------
class ResendPasswordResetOTPAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from accounts.views import send_professional_otp_email
        from django.core.cache import cache

        identifier = request.data.get("identifier") or request.data.get("email")
        user_id = request.data.get("user_id") or (request.session.get('password_reset_user_id') if hasattr(request, 'session') else None)

        user = None
        if identifier:
            user = find_user_by_identifier(identifier)
        elif user_id:
            user = User.objects.filter(id=user_id).first()

        if not user:
            return Response({"detail": "User not found. Please initiate password reset again."}, status=status.HTTP_404_NOT_FOUND)

        otp = str(random.randint(100000, 999999))

        cache_key = f"pwd_reset_otp_{user.id}"
        cache.set(cache_key, otp, timeout=300)
        cache.set(f"pwd_reset_user_{user.id}", user.id, timeout=300)

        if hasattr(request, 'session'):
            request.session['password_reset_user_id'] = user.id
            request.session['password_reset_otp'] = otp
            request.session['otp_created_at'] = time.time()

        send_professional_otp_email(
            recipient_email=user.email,
            otp_code=otp,
            subject="🔄 New Password Reset OTP - SmartKuri",
            title_text="New Password Reset OTP",
            body_text="Here is your requested new verification code to reset your SmartKuri account password.",
            target_name="Unified Single Password Reset"
        )

        return Response({
            "status": "success",
            "detail": f"New OTP sent to {user.email}",
            "email": user.email
        }, status=status.HTTP_200_OK)


# ---------------------------------------
# PASSWORD RESET CONFIRM
# ---------------------------------------
class PasswordResetConfirmAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from django.core.cache import cache

        identifier = request.data.get("identifier") or request.data.get("email")
        user_id = request.data.get("user_id") or (request.session.get('password_reset_user_id') if hasattr(request, 'session') else None)

        user = None
        if identifier:
            user = find_user_by_identifier(identifier)
        elif user_id:
            user = User.objects.filter(id=user_id).first()

        if not user:
            return Response({"detail": "Session expired or invalid user. Please try again."}, status=status.HTTP_400_BAD_REQUEST)

        otp_entered = str(request.data.get("otp") or "").strip()
        password1 = request.data.get("password1") or request.data.get("new_password") or request.data.get("password")
        password2 = request.data.get("password2") or request.data.get("confirm_password")

        cached_otp = cache.get(f"pwd_reset_otp_{user.id}")
        session_otp = request.session.get('password_reset_otp') if hasattr(request, 'session') else None
        valid_otp = cached_otp or session_otp

        if not valid_otp:
            return Response({"detail": "OTP has expired. Please click Resend OTP."}, status=status.HTTP_400_BAD_REQUEST)

        if str(otp_entered) != str(valid_otp):
            return Response({"detail": "Invalid OTP code. Please check and try again."}, status=status.HTTP_400_BAD_REQUEST)

        if not password1 or not password2:
            return Response({"detail": "Both password fields are required."}, status=status.HTTP_400_BAD_REQUEST)

        if password1 != password2:
            return Response({"detail": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        if len(password1) < 8:
            return Response({"detail": "Password must be at least 8 characters long."}, status=status.HTTP_400_BAD_REQUEST)

        # Set user password
        user.set_password(password1)
        user.save()

        # Synchronize all associated Member objects
        Member.objects.filter(Q(user=user) | Q(email=user.email) | Q(phone=user.username)).update(
            is_first_login=False
        )

        # Clear cache & session
        cache.delete(f"pwd_reset_otp_{user.id}")
        cache.delete(f"pwd_reset_user_{user.id}")
        if hasattr(request, 'session'):
            request.session.pop('password_reset_user_id', None)
            request.session.pop('password_reset_otp', None)
            request.session.pop('otp_created_at', None)

        return Response({
            "status": "success",
            "detail": "Password reset successful! You can now login with your new password across all portals."
        }, status=status.HTTP_200_OK)


# ---------------------------------------
# FIRST LOGIN CHANGE PASSWORD
# ---------------------------------------
class FirstLoginChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        # =====================================
        # 👤 Get member
        # =====================================
        member = Member.objects.filter(user=request.user).first()

        if not member:
            return Response(
                {
                    "status": "error",
                    "detail": "Member not found."
                },
                status=status.HTTP_404_NOT_FOUND
            )

        # =====================================
        # 🚫 Already changed password
        # =====================================
        if not member.is_first_login:
            return Response(
                {
                    "status": "error",
                    "detail": "Password already changed."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =====================================
        # 🔑 Get passwords
        # =====================================
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        # =====================================
        # ⚠️ Validation
        # =====================================
        if not new_password or not confirm_password:
            return Response(
                {
                    "status": "error",
                    "detail": "Both password fields are required."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Minimum password length
        if len(new_password) < 8:
            return Response(
                {
                    "status": "error",
                    "detail": "Password must be at least 8 characters."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Password mismatch
        if new_password != confirm_password:
            return Response(
                {
                    "status": "error",
                    "detail": "Passwords do not match."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # =====================================
        # 🔐 Change password
        # =====================================
        user = request.user

        user.set_password(new_password)
        user.save()

        # Keep user logged in
        update_session_auth_hash(request, user)

        # =====================================
        # ✅ First login completed
        # =====================================
        member.is_first_login = False
        member.save()

        # =====================================
        # ✅ Success response
        # =====================================
        return Response(
            {
                "status": "success",
                "detail": "Password changed successfully.",
                "redirect_to": "members:member_dashboard",
                "first_login": False
            },
            status=status.HTTP_200_OK
        )


# =====================================
# 🌐 USER KURIS LIST (Multi-Kuri Support)
# =====================================
class UserKurisAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        admin_groups = []
        collector_groups = []
        member_groups = []

        # 1. Admin groups
        staff_prof = StaffProfile.objects.filter(user=user).first()
        if staff_prof and staff_prof.role in ['group_admin', 'admin']:
            owned = ChittiGroup.objects.filter(
                Q(owner=user) | Q(collector=staff_prof) | Q(parent_group__owner=user),
                is_active=True
            ).distinct()
            for g in owned:
                admin_groups.append({
                    'id': g.id,
                    'name': g.name,
                    'code': g.code,
                    'monthly_amount': float(g.monthly_amount or 0),
                    'total_amount': float(g.total_amount or 0),
                    'duration_months': g.duration_months or 1,
                })

        # 2. Collector groups - strictly groups assigned to this collector
        if staff_prof:
            c_groups = staff_prof.assigned_chitti_groups.filter(is_active=True)
            if not c_groups.exists() and staff_prof.group and staff_prof.group.is_active:
                c_groups = ChittiGroup.objects.filter(id=staff_prof.group.id)
            fallback = ChittiGroup.objects.filter(collector=staff_prof, is_active=True)
            c_groups = (c_groups | fallback).distinct()
            for g in c_groups:
                collector_groups.append({
                    'id': g.id,
                    'name': g.name,
                    'code': g.code,
                    'monthly_amount': float(g.monthly_amount or 0),
                    'duration_months': g.duration_months or 1,
                })

        # 3. Member groups - strictly for THIS user
        user_match = Q(user=user)
        if user.email:
            user_match |= Q(email=user.email)
        if user.username:
            user_match |= Q(phone=user.username)

        members = Member.objects.filter(user_match).select_related('assigned_chitti_group').distinct()

        seen_group_ids = set()
        for m in members:
            if m.assigned_chitti_group and m.assigned_chitti_group.is_active:
                gid = m.assigned_chitti_group.id
                if gid not in seen_group_ids:
                    seen_group_ids.add(gid)
                    g = m.assigned_chitti_group
                    member_groups.append({
                        'id': g.id,
                        'name': g.name,
                        'code': g.code,
                        'monthly_amount': float(g.monthly_amount or 0),
                        'total_amount': float(g.total_amount or 0),
                        'duration_months': g.duration_months or 1,
                        'member_id': m.id,
                    })
            for cm in m.chitti_memberships.filter(group__is_active=True).select_related('group'):
                gid = cm.group.id
                if gid not in seen_group_ids:
                    seen_group_ids.add(gid)
                    g = cm.group
                    member_groups.append({
                        'id': g.id,
                        'name': g.name,
                        'code': g.code,
                        'monthly_amount': float(g.monthly_amount or 0),
                        'total_amount': float(g.total_amount or 0),
                        'duration_months': g.duration_months or 1,
                        'member_id': m.id,
                    })

        return Response({
            "has_admin": len(admin_groups) > 0,
            "has_collector": len(collector_groups) > 0,
            "has_member": len(member_groups) > 0,
            "admin_groups": admin_groups,
            "collector_groups": collector_groups,
            "member_groups": member_groups,
        }, status=status.HTTP_200_OK)


# =====================================
# USER LOOKUP API (PUBLIC - FOR LOGIN DISCOVERY)
# =====================================
class UserLookupAPIView(APIView):
    permission_classes = []
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        return self.post(request)

    def post(self, request):
        identifier = ''
        if hasattr(request, 'data') and request.data:
            identifier = (request.data.get('identifier') or '').strip()
        if not identifier and hasattr(request, 'query_params'):
            identifier = (request.query_params.get('identifier') or '').strip()
        if not identifier and hasattr(request, 'GET'):
            identifier = (request.GET.get('identifier') or '').strip()

        if not identifier:
            return Response({"exists": False, "items": []}, status=status.HTTP_200_OK)

        # Find all matching users
        matched_users = list(User.objects.filter(
            Q(username__iexact=identifier) | Q(email__iexact=identifier)
        ))

        # Check StaffProfile
        staff_by_phone = StaffProfile.objects.filter(
            Q(phone=identifier) | Q(user__email__iexact=identifier)
        ).select_related('user')
        for s in staff_by_phone:
            if s.user and s.user not in matched_users:
                matched_users.append(s.user)

        # Check Member
        members_by_phone = Member.objects.filter(
            Q(phone=identifier) | Q(email__iexact=identifier)
        ).select_related('user')
        for m in members_by_phone:
            if m.user and m.user not in matched_users:
                matched_users.append(m.user)

        if not matched_users:
            return Response({"exists": False, "items": []}, status=status.HTTP_200_OK)

        primary_user = matched_users[0]
        items = []
        seen_keys = set()

        for u in matched_users:
            # 1. Staff Profiles
            staff_profiles = StaffProfile.objects.filter(
                Q(user=u) | Q(user__email__iexact=u.email)
            ).distinct()

            for sp in staff_profiles:
                if sp.role in ['group_admin', 'admin']:
                    key = 'portal_group_admin'
                    if key not in seen_keys:
                        seen_keys.add(key)
                        items.append({
                            "type": "group_admin",
                            "title": "Group Admin Portal",
                            "subtitle": "Manage all your Kuri groups",
                            "group_id": None,
                            "code": "ADMIN",
                            "icon": "crown",
                        })
                    
                    # Group Admin also has Collector Portal access
                    c_key = 'portal_collector'
                    if c_key not in seen_keys:
                        seen_keys.add(c_key)
                        items.append({
                            "type": "collector",
                            "title": "Collector Portal",
                            "subtitle": "Collection & receipt dashboard",
                            "group_id": None,
                            "code": "COLLECTOR",
                            "icon": "cash",
                        })

                elif sp.role == 'collector':
                    # Collector groups
                    c_groups = sp.assigned_chitti_groups.filter(is_active=True)
                    if not c_groups.exists() and sp.group and sp.group.is_active:
                        c_groups = ChittiGroup.objects.filter(id=sp.group.id)
                    fallback = ChittiGroup.objects.filter(collector=sp, is_active=True)
                    c_groups = (c_groups | fallback).distinct()

                    if c_groups.exists():
                        for g in c_groups:
                            key = f"collector_group_{g.id}"
                            if key not in seen_keys:
                                seen_keys.add(key)
                                items.append({
                                    "type": "collector",
                                    "title": f"Collector - {g.name}",
                                    "subtitle": f"Code: {g.code}",
                                    "group_id": g.id,
                                    "code": g.code,
                                    "icon": "cash",
                                })
                    else:
                        key = 'portal_collector'
                        if key not in seen_keys:
                            seen_keys.add(key)
                            items.append({
                                "type": "collector",
                                "title": "Collector Portal",
                                "subtitle": "Collection & receipt dashboard",
                                "group_id": None,
                                "code": "COLLECTOR",
                                "icon": "cash",
                            })

            # 2. Member Groups
            user_match = Q(user=u)
            if u.email:
                user_match |= Q(email__iexact=u.email)
            if u.username:
                user_match |= Q(phone=u.username)
            user_match |= Q(phone=identifier)

            m_records = Member.objects.filter(user_match).select_related('assigned_chitti_group').distinct()
            for m in m_records:
                if m.assigned_chitti_group and m.assigned_chitti_group.is_active:
                    g = m.assigned_chitti_group
                    key = f"member_group_{g.id}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        items.append({
                            "type": "member",
                            "title": g.name,
                            "subtitle": f"Code: {g.code} (Member)",
                            "group_id": g.id,
                            "code": g.code,
                            "icon": "member",
                        })
                for cm in m.chitti_memberships.filter(group__is_active=True).select_related('group'):
                    g = cm.group
                    key = f"member_group_{g.id}"
                    if key not in seen_keys:
                        seen_keys.add(key)
                        items.append({
                            "type": "member",
                            "title": g.name,
                            "subtitle": f"Code: {g.code} (Member)",
                            "group_id": g.id,
                            "code": g.code,
                            "icon": "member",
                        })

        return Response({
            "exists": True,
            "username": primary_user.username,
            "name": primary_user.get_full_name() or primary_user.username,
            "items": items,
        }, status=status.HTTP_200_OK)


# =====================================
# 🔐 CHANGE PASSWORD API
# =====================================
class ChangePasswordAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        current_password = request.data.get("current_password", "").strip()
        new_password = request.data.get("new_password", "").strip()
        confirm_password = request.data.get("confirm_password", "").strip()

        if not current_password or not new_password or not confirm_password:
            return Response(
                {"error": "All fields (current password, new password, confirm password) are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_password(current_password):
            return Response(
                {"error": "Current password does not match our records."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if len(new_password) < 6:
            return Response(
                {"error": "New password must be at least 6 characters long."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_password != confirm_password:
            return Response(
                {"error": "New password and confirmation do not match."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if current_password == new_password:
            return Response(
                {"error": "New password cannot be the same as your current password."},
                status=status.HTTP_400_BAD_REQUEST
            )

        user.set_password(new_password)
        user.save()

        return Response(
            {
                "success": True,
                "message": "Password changed successfully."
            },
            status=status.HTTP_200_OK
        )