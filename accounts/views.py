from builtins import float, hasattr, int, print, str
import string
import uuid
import random
import time
from django.views.decorators.csrf import csrf_exempt
import razorpay
from dateutil.relativedelta import relativedelta
from datetime import date
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Sum
from accounts.decorators import admin_required, collector_required,group_admin_required, member_required
from subscriptions.models import GroupSubscription, SubscriptionPlan
from .models import StaffProfile
from accounts.decorators import admin_required
from .forms import CashCollectorCreateForm, GroupSignUpForm
from members.models import Member
from chitti.models import ChittiGroup, ChittiMember
from payments.models import Payment
from django.contrib.auth import get_user_model
import time
from django.utils.timezone import now
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from django.contrib.auth.decorators import login_required
import random
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from django.db import transaction
from django.utils.crypto import get_random_string

def group_signup(request):
    if request.method == 'POST':
        form = GroupSignUpForm(request.POST)
        if form.is_valid():
            group_name = form.cleaned_data['group_name']
            phone = form.cleaned_data['phone']
            email = form.cleaned_data['email']
            password = form.cleaned_data['password1']
            plan = form.cleaned_data['plan']

            # 1️⃣ Group name check
            if ChittiGroup.objects.filter(name=group_name).exists():
                messages.error(request, "Group name already exists.")
                return redirect('accounts:group_signup')

            # 2️⃣ Email check → already used by another group?
            if User.objects.filter(email=email).exists():
                messages.error(request, f"The email '{email}' is already used by another group.")
                return redirect('accounts:group_signup')

            # 3️⃣ OTP generate
            otp = random.randint(100000, 999999)
            request.session['pending_group_data'] = {
                'group_name': group_name,
                'phone': phone,
                'email': email,
                'password': password,
                'plan_id': plan.id,
                'plan_price': float(plan.price),
                'otp': otp,
                'otp_created_at': time.time(),
                'otp_verified': False,
                'payment_done': False,
                'otp_sent': True
            }

            # 4️⃣ Send OTP mail
            send_mail(
                "SmartKuri - Group Signup OTP",
                f"Your OTP for group '{group_name}' signup is: {otp}",
                settings.DEFAULT_FROM_EMAIL,
                [email],
                fail_silently=False
            )

            messages.success(request, "OTP sent! Verify to proceed to payment.")
            return redirect('accounts:verify_group_otp')
    else:
        form = GroupSignUpForm()

    plans = SubscriptionPlan.objects.filter(is_active=True)
    return render(request, 'accounts/group_signup.html', {'form': form, 'plans': plans})



# VERIFY OTP
# -----------------------------
def verify_group_otp(request):
    data = request.session.get('pending_group_data')

    if not data:
        messages.error(request, "No signup data found.")
        return redirect('accounts:group_signup')

    if request.method == 'POST':
        otp_entered = request.POST.get('otp')

        # ⏰ OTP expiry (10 minutes)
        if time.time() - data['otp_created_at'] > 600:
            messages.error(request, "OTP expired. Please signup again.")
            del request.session['pending_group_data']
            return redirect('accounts:group_signup')

        if str(otp_entered) == str(data['otp']):
            data['otp_verified'] = True

            # 🔥 IMPORTANT PART
            plan = SubscriptionPlan.objects.get(id=data['plan_id'])

            # ✅ FREE / UNLIMITED PLAN → NO PAYMENT
            if plan.price <= 0 or getattr(plan, 'is_unlimited', False):
                data['payment_done'] = True
                request.session['pending_group_data'] = data
                messages.success(
                    request,
                    "OTP verified! Free plan activated. Creating group..."
                )
                return redirect('accounts:create_group_after_payment')

            # 💳 PAID PLAN → GO TO PAYMENT
            request.session['pending_group_data'] = data
            messages.success(request, "OTP verified! Proceed to payment.")
            return redirect('accounts:payment_page')

        else:
            messages.error(request, "Invalid OTP. Try again.")

    return render(request, 'accounts/verify_group_otp.html', {'data': data})



# -----------------------------
# PAYMENT PAGE
# -----------------------------
def payment_page(request):
    data = request.session.get('pending_group_data')
    if not data or not data.get('otp_verified'):
        messages.error(request, "Verify OTP first!")
        return redirect('accounts:verify_group_otp')

    plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

    # Duration display
    duration_months = plan.duration_days // 30
    remaining_days = plan.duration_days % 30
    if duration_months > 0 and remaining_days > 0:
        duration_display = f"{duration_months} Month ({remaining_days} Days)"
    elif duration_months > 0:
        duration_display = f"{duration_months} Month"
    else:
        duration_display = f"{plan.duration_days} Days"

    data.update({
        "plan_name": plan.name,
        "plan_price": float(plan.price),
        "duration_months": duration_months,
        "duration_days": plan.duration_days,
        "duration_display": duration_display,
        "max_members": plan.max_members,
        "is_unlimited": getattr(plan, 'is_unlimited', False),  # <-- important
    })
    request.session['pending_group_data'] = data

    # Skip Razorpay if plan is free/unlimited
    if plan.price <= 0 or getattr(plan, 'is_unlimited', False):
        data['payment_done'] = True
        request.session['pending_group_data'] = data
        messages.success(request, "Unlimited / Free plan selected. No payment required.")
        return redirect('accounts:create_group_after_payment')

    # Razorpay order for paid plans
    amount_paise = int(plan.price * 100)
    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"group_signup_{data['email']}",
        "payment_capture": 1
    })
    request.session['razorpay_order_id'] = order['id']

    return render(request, 'accounts/payment_page.html', {
        "data": data,
        "razorpay_order_id": order['id'],
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "amount": amount_paise,
        "currency": "INR",
    })


# -----------------------------
# PAYMENT SUCCESS
# -----------------------------
@csrf_exempt
def payment_success(request):
    data = request.session.get('pending_group_data')
    if not data or not data.get('otp_verified'):
        messages.error(request,"Session expired!")
        return redirect('accounts:group_signup')

    if request.method=="POST":
        payment_id = request.POST.get('razorpay_payment_id')
        order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature
            })
            data['payment_done'] = True
            request.session['pending_group_data'] = data
            messages.success(request,"Payment successful! Creating group...")
            return redirect('accounts:create_group_after_payment')
        except razorpay.errors.SignatureVerificationError:
            messages.error(request,"Payment verification failed.")
            return redirect('accounts:payment_page')


@transaction.atomic
def create_group_after_payment(request):
    data = request.session.get('pending_group_data')

    if not data or not data.get('payment_done'):
        messages.error(request, "Payment not completed!")
        return redirect('accounts:payment_page')

    plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

    # ----------------------------------
    # ✅ PLAN GROUP LIMIT CHECK (FIXED)
    # ----------------------------------
    existing_groups_count = GroupSubscription.objects.filter(
        group__owner__staffprofile__role='group_admin',
        plan=plan,
        is_active=True
    ).count()

    if plan.max_groups != 0 and existing_groups_count >= plan.max_groups:
        messages.error(
            request,
            f"You have reached your group creation limit for the {plan.name} plan."
        )
        return redirect('accounts:group_admin_dashboard')

    # ----------------------------------
    # ✅ CREATE ADMIN USER
    # ----------------------------------
    username = f"group_{get_random_string(8)}"

    admin_user = User.objects.create_user(
        username=username,
        email=data['email'],
        password=data['password'],
        first_name=data['group_name']
    )

    # ----------------------------------
    # ✅ CREATE CHITTI GROUP
    # ----------------------------------
    monthly_amount = (
        round(plan.price / plan.duration_days * 30, 2)
        if plan.price > 0 else 0
    )

    group = ChittiGroup.objects.create(
        name=data['group_name'],
        owner=admin_user,
        total_amount=plan.price,
        monthly_amount=monthly_amount,
        duration_months=plan.duration_days // 30,
        start_date=timezone.now().date()
    )

    # ----------------------------------
    # ✅ CREATE STAFF PROFILE
    # ----------------------------------
    staff_profile = StaffProfile.objects.create(
        user=admin_user,
        group=group,
        phone=data['phone'],
        role='group_admin',
        is_subscribed=True
    )

    # ----------------------------------
    # ✅ PAYMENT ENTRY (ONLY IF PAID PLAN)
    # ----------------------------------
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

    # ----------------------------------
    # ✅ GROUP SUBSCRIPTION
    # ----------------------------------
    GroupSubscription.objects.create(
        group=group,
        plan=plan,
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timezone.timedelta(days=plan.duration_days),
        is_active=True
    )

    # ----------------------------------
    # ✅ CLEAR SESSION
    # ----------------------------------
    del request.session['pending_group_data']

    messages.success(request, f"Group '{group.name}' created successfully!")

    # ----------------------------------
    # ✅ AUTO LOGIN (MULTI BACKEND FIX)
    # ----------------------------------
    admin_user.backend = 'django.contrib.auth.backends.ModelBackend'
    login(request, admin_user)

    return redirect('accounts:group_admin_dashboard')

# RESEND OTP
# ---------------------------------------
def resend_group_otp(request):
    data = request.session.get('pending_group_data')
    if not data:
        messages.error(request, "No signup data found. Please signup again.")
        return redirect('accounts:group_signup')

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

    messages.success(request, "New OTP sent! Check your email.")
    return redirect('accounts:verify_group_otp')


User = get_user_model()

def login_view(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier')
        password = request.POST.get('password')
        user = None

        # 1️⃣ Authenticate by username
        user = authenticate(request, username=identifier, password=password)

        # 2️⃣ Authenticate by email (safe with filter)
        if user is None:
            u = User.objects.filter(email=identifier).first()
            if u and u.check_password(password):
                user = u

        # 3️⃣ Authenticate member by phone (safe with filter)
        if user is None:
            member = Member.objects.filter(phone=identifier).first()
            if member and member.user and member.user.check_password(password):
                user = member.user

        # 4️⃣ Authenticate staff by phone (already safe with filter().first())
        if user is None:
            staff = StaffProfile.objects.filter(phone=identifier).first()
            if staff and staff.user.check_password(password):
                user = staff.user

        # 5️⃣ Login & redirect
        if user:
            login(request, user)

            # Staff redirects
            if hasattr(user, 'staffprofile'):
                role = user.staffprofile.role
                if role == 'admin':
                    return redirect('adminpanel:dashboard')
                elif role == 'collector':
                    return redirect('accounts:collector_dashboard')
                elif role == 'group_admin':
                    return redirect('accounts:group_admin_dashboard')

            # Member dashboard
            return redirect('members:member_dashboard')

        messages.error(request, "Invalid credentials. Use username, email, or phone number.")
        return redirect('accounts:login')

    return render(request, 'accounts/login.html')


@login_required
def change_password(request):
    member = Member.objects.filter(user=request.user).first()
    if not member:
        return redirect('accounts:login')

    # Already changed
    if not member.is_first_login:
        return redirect('members:member_dashboard')

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match")
        else:
            user = request.user
            user.set_password(new_password)
            user.save()

            # ✅ KEEP SESSION
            update_session_auth_hash(request, user)

            member.is_first_login = False
            member.save()

            messages.success(request, "Password changed successfully")
            return redirect('members:member_dashboard')

    return render(request, 'member/change_password.html')

# ------------------------
# LOGOUT
# ------------------------
def logout_view(request):
    logout(request)
    return redirect('accounts:login')

# ---------------------------------------
# PASSWORD RESET REQUEST
# ---------------------------------------
def password_reset_request(request):
    if request.method == "POST":
        identifier = request.POST.get("identifier")
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

        if user:
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
            messages.success(request, "OTP sent to your email.")
            return redirect("accounts:password_reset_verify")
        else:
            messages.error(request, "No user found with this email or phone.")

    return render(request, "accounts/password_reset.html")


# ---------------------------------------
# PASSWORD RESET CONFIRM
# ---------------------------------------
def password_reset_confirm(request):
    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, "Session expired. Try again.")
        return redirect("accounts:password_reset")

    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        otp_entered = request.POST.get("otp")
        password1 = request.POST.get("password1")
        password2 = request.POST.get("password2")

        otp_saved = request.session.get('password_reset_otp')
        otp_time = request.session.get('otp_created_at')

        if not otp_saved or (time.time() - otp_time) > 300:
            messages.error(request, "OTP expired. Please try again.")
            return redirect("accounts:password_reset")

        if str(otp_entered) != str(otp_saved):
            messages.error(request, "Invalid OTP.")
        elif password1 != password2:
            messages.error(request, "Passwords do not match.")
        else:
            user.set_password(password1)
            user.save()
            request.session.pop('password_reset_user_id', None)
            request.session.pop('password_reset_otp', None)
            request.session.pop('otp_created_at', None)
            messages.success(request, "Password reset successful! You can now login.")
            return redirect("accounts:login")

    return render(request, "accounts/password_reset_verify.html", {"user": user})




@group_admin_required
def group_admin_dashboard(request):
    today = timezone.now().date()
    user = request.user

    # ================= Groups =================
    groups = ChittiGroup.objects.filter(owner=user)
    total_groups = groups.count()
    active_groups = groups.filter(is_active=True).count()

    # ================= Members =================
    total_members = ChittiMember.objects.filter(group__owner=user).count()

    # ================= This Month Collection =================
    month_start = today.replace(day=1)
    this_month_collection = Payment.objects.filter(
        group__owner=user,
        payment_status='success',
        paid_date__gte=month_start
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= Total Collected =================
    total_received = Payment.objects.filter(
        group__owner=user,
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= Context =================
    context = {
        'total_groups': total_groups,
        'active_groups': active_groups,
        'total_members': total_members,
        'this_month_collection': this_month_collection,
        'total_received': total_received,
        'groups': groups,  # include groups for table rendering
    }

    return render(request, 'chitti/group_admin_dashboard.html', context)






from datetime import date
from django.db.models import Sum

@collector_required
def collector_dashboard(request):

    collector = request.user.staffprofile

    # Today collection
    today_collection = Payment.objects.filter(
        collected_by=collector,
        paid_date=date.today(),
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Monthly collection
    monthly_collection = Payment.objects.filter(
        collected_by=collector,
        paid_date__month=date.today().month,
        paid_date__year=date.today().year,
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Total collection
    total_collection = Payment.objects.filter(
        collected_by=collector,
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Active members
    active_members = Member.objects.filter(
        collections__collected_by=collector
    ).distinct().count()

    # Recent 10 payments
    recent_payments = Payment.objects.filter(
        collected_by=collector,
        payment_status='success'
    ).order_by('-paid_date', '-paid_time')[:10]

    context = {
        'today_collection': today_collection,
        'monthly_collection': monthly_collection,
        'total_collection': total_collection,
        'active_members': active_members,
        'recent_payments': recent_payments,
    }

    return render(request, 'collector/collector_dashboard.html', context)






