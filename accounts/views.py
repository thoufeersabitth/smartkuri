from builtins import float, hasattr, int, print, str
from decimal import Decimal
import string
import uuid
from django.db.models import Sum, Q
import random
import time
from django.db import models
from django.views.decorators.csrf import csrf_exempt
import razorpay
from dateutil.relativedelta import relativedelta
from datetime import date, datetime, timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
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
from payments.models import Payment
from django.utils.crypto import get_random_string

import random
from django.shortcuts import render, redirect
from django.contrib import messages
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .forms import GroupSignUpForm
from .models import User, StaffProfile


# ---------------------------------------
# PRO MAX STYLED HTML EMAIL DISPATCHER
# ---------------------------------------
def send_professional_otp_email(recipient_email, otp_code, action_type="reset", target_name="", subject=None, title_text=None, body_text=None):
    """
    Sends an ultra-professional HTML Email for Password Reset or Registration OTP.
    """
    if not subject:
        subject = "SmartKuri - Password Reset Verification OTP" if action_type == "reset" else "SmartKuri - Account Registration Verification OTP"
    if not title_text:
        title_text = "Password Reset Request" if action_type == "reset" else "Account Registration"
    if not body_text:
        body_text = "We received a request to reset your password. Use the verification OTP below to proceed." if action_type == "reset" else "Welcome to SmartKuri! Please use the verification OTP below to complete your registration."
    badge_title = "Target Account / Kuri Group" if action_type == "reset" else "Registration Scope"

    account_badge_html = ""
    if target_name:
        account_badge_html = f"""
        <div style="background-color: #f8fafc; border-left: 4px solid #6366f1; padding: 14px 18px; border-radius: 12px; margin-bottom: 24px; text-align: left;">
            <span style="font-size: 11px; font-weight: 800; text-transform: uppercase; color: #64748b; letter-spacing: 0.8px; display: block; margin-bottom: 4px;">{badge_title}</span>
            <span style="font-size: 16px; font-weight: 800; color: #1e293b;">{target_name}</span>
        </div>
        """

    html_message = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color: #f1f5f9; padding: 40px 12px;">
            <tr>
                <td align="center">
                    <table role="presentation" width="100%" style="max-width: 520px; background: #ffffff; border-radius: 28px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.08); overflow: hidden; border: 1px solid #e2e8f0;" cellspacing="0" cellpadding="0">
                        
                        <!-- HEADER -->
                        <tr>
                            <td style="background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%); padding: 36px 30px; text-align: center;">
                                <div style="width: 56px; height: 56px; background: rgba(255,255,255,0.2); border-radius: 18px; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 12px;">
                                    <span style="font-size: 28px; color: #ffffff;">💼</span>
                                </div>
                                <h1 style="color: #ffffff; margin: 0; font-size: 26px; font-weight: 900; letter-spacing: -0.5px;">SmartKuri</h1>
                                <p style="color: rgba(255,255,255,0.85); margin: 4px 0 0 0; font-size: 13px; font-weight: 600;">Digital Chitty Management Platform</p>
                            </td>
                        </tr>

                        <!-- BODY -->
                        <tr>
                            <td style="padding: 40px 36px;">
                                <h2 style="color: #0f172a; margin: 0 0 12px 0; font-size: 22px; font-weight: 800; text-align: center;">{title_text}</h2>
                                <p style="color: #475569; margin: 0 0 24px 0; font-size: 14px; line-height: 1.6; text-align: center;">
                                    {body_text}
                                </p>

                                {account_badge_html}

                                <!-- OTP BOX -->
                                <div style="background: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 20px; padding: 24px; text-align: center; margin-bottom: 24px;">
                                    <span style="font-size: 12px; font-weight: 800; text-transform: uppercase; color: #64748b; letter-spacing: 1px; display: block; margin-bottom: 8px;">Verification Code (OTP)</span>
                                    <div style="font-size: 40px; font-weight: 900; color: #4f46e5; letter-spacing: 10px; font-family: 'Courier New', Courier, monospace;">{otp_code}</div>
                                    <span style="font-size: 12px; color: #ef4444; font-weight: 700; margin-top: 8px; display: block;">⏱ Valid for 5 minutes only</span>
                                </div>

                                <div style="background-color: #fffbeb; border: 1px solid #fef3c7; border-radius: 14px; padding: 14px 16px; margin-bottom: 20px;">
                                    <p style="color: #b45309; margin: 0; font-size: 13px; line-height: 1.5; font-weight: 600;">
                                        <strong>🔒 Security Note:</strong> If you did not request this OTP, please ignore this email. Never share your verification code with anyone.
                                    </p>
                                </div>
                            </td>
                        </tr>

                        <!-- FOOTER -->
                        <tr>
                            <td style="background-color: #f8fafc; padding: 24px 36px; text-align: center; border-top: 1px solid #f1f5f9;">
                                <p style="color: #64748b; margin: 0 0 4px 0; font-size: 12px; font-weight: 700;">SmartKuri Security System</p>
                                <p style="color: #94a3b8; margin: 0; font-size: 11px;">Automated verification message &bull; Do not reply</p>
                            </td>
                        </tr>

                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """

    plain_message = f"SmartKuri OTP Verification: {otp_code}. Valid for 5 minutes. Scope: {target_name or 'SmartKuri'}"

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False
        )
    except Exception as e:
        print("OTP Email send error:", e)


# ✅ SIGNUP VIEW
def group_signup(request):
    if request.method == 'POST':
        form = GroupSignUpForm(request.POST)

        if form.is_valid():
            data = form.cleaned_data

            if User.objects.filter(email=data['email']).exists():
                form.add_error('email', "This email is already registered.")
            else:
                otp = str(random.randint(100000, 999999))

                request.session['pending_group_data'] = {
                    'phone': data['phone'],
                    'email': data['email'],
                    'password': data['password1'],
                    'otp': otp
                }

                try:
                    send_professional_otp_email(
                        recipient_email=data['email'],
                        otp_code=otp,
                        action_type="registration",
                        target_name="Group Admin Account Registration"
                    )
                    return redirect('accounts:verify_group_otp')
                except Exception as e:
                    print("Email error:", e)
                    messages.error(request, "Failed to send OTP. Please try again.")

        else:
            print("FORM ERROR:", form.errors)
    else:
        form = GroupSignUpForm()

    return render(request, 'accounts/group_signup.html', {'form': form})


# ✅ OTP VERIFY VIEW
# ✅ OTP VERIFY VIEW
def verify_group_otp(request):
    data = request.session.get('pending_group_data')

    # ✅ session illenkil redirect back
    if not data:
        messages.error(request, "Session expired. Please signup again.")
        return redirect('accounts:group_signup')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp')

        # ✅ OTP match check
        if entered_otp == data['otp']:
            try:
                with transaction.atomic():
                    # ✅ Create User properly with Hashed Password
                    if not User.objects.filter(email=data['email']).exists():
                        user = User.objects.create_user(
                            username=data['email'], # Using email as username
                            email=data['email']
                        )
                        user.set_password(data['password']) # 👈 IMPORTANT: This hashes the password
                        user.save()
                    else:
                        user = User.objects.get(email=data['email'])

                    # ✅ Create/Update StaffProfile
                    # Group is None here. User will create group AFTER login.
                    StaffProfile.objects.update_or_create(
                        user=user,
                        defaults={
                            'phone': data['phone'],
                            'role': 'group_admin',
                            'group': None, # 👈 This stays None for now
                            'is_subscribed': False
                        }
                    )

                # ✅ Clear session
                request.session.pop('pending_group_data', None)

                messages.success(request, "Signup successful! Please login to set up your group.")
                return redirect('accounts:login')

            except Exception as e:
                messages.error(request, f"Error during registration: {str(e)}")
        else:
            messages.error(request, "Invalid OTP. Please check again.")

    return render(request, 'accounts/verify_group_otp.html')

# -----------------------------
def payment_page(request):
    data = request.session.get('pending_group_data')

   
    if not data:
        messages.error(request, "Session expired.")
        return redirect('accounts:group_signup')

    if not data.get('otp_verified'):
        messages.error(request, "Verify OTP first!")
        return redirect('accounts:verify_group_otp')

    plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

    # 📅 Duration display
    duration_months = plan.duration_days // 30
    remaining_days = plan.duration_days % 30

    if duration_months > 0 and remaining_days > 0:
        duration_display = f"{duration_months} Month ({remaining_days} Days)"
    elif duration_months > 0:
        duration_display = f"{duration_months} Month"
    else:
        duration_display = f"{plan.duration_days} Days"

    # ✅ UPDATE SESSION
    data.update({
        "plan_name": plan.name,
        "plan_price": float(plan.price),
        "duration_months": duration_months,
        "duration_days": plan.duration_days,
        "duration_display": duration_display,
        "max_members": plan.max_members,
        "is_unlimited": getattr(plan, 'is_unlimited', False),
    })
    request.session['pending_group_data'] = data

    # 🟢 FREE PLAN
    if plan.price <= 0 or getattr(plan, 'is_unlimited', False):
        data['payment_done'] = True
        request.session['pending_group_data'] = data

        return redirect('accounts:create_group_after_payment')

    # 🔵 PAID PLAN
    try:
        amount_paise = int(plan.price * 100)

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )

        order = client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": f"group_{data['email']}",
            "payment_capture": 1
        })

        # ✅ store both order id + amount (important)
        request.session['razorpay_order_id'] = order['id']
        request.session['razorpay_amount'] = amount_paise

    except Exception as e:
        messages.error(request, f"Payment init failed: {str(e)}")
        return redirect('accounts:group_signup')

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

    # 🔒 Session + OTP check
    if not data:
        messages.error(request, "Session expired!")
        return redirect('accounts:group_signup')

    if not data.get('otp_verified'):
        messages.error(request, "OTP not verified!")
        return redirect('accounts:verify_group_otp')

    # ❗ Only POST allowed
    if request.method != "POST":
        return redirect('accounts:payment_page')

    payment_id = request.POST.get('razorpay_payment_id')
    order_id = request.POST.get('razorpay_order_id')
    signature = request.POST.get('razorpay_signature')

    session_order_id = request.session.get('razorpay_order_id')

    # 🔒 Order ID validation (VERY IMPORTANT)
    if not session_order_id or order_id != session_order_id:
        messages.error(request, "Invalid payment request!")
        return redirect('accounts:payment_page')

    client = razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )

    try:
        # ✅ Signature verify
        client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        })

        # 🛑 Prevent duplicate execution
        if data.get('payment_done'):
            return redirect('accounts:create_group_after_payment')

        # ✅ Mark payment success
        data['payment_done'] = True
        request.session['pending_group_data'] = data

        # 🧹 Clean Razorpay session
        request.session.pop('razorpay_order_id', None)

        messages.success(request, "Payment successful! Creating group...")
        return redirect('accounts:create_group_after_payment')

    except razorpay.errors.SignatureVerificationError:
        messages.error(request, "Payment verification failed.")
        return redirect('accounts:payment_page')

    except Exception as e:
        messages.error(request, f"Error: {str(e)}")
        return redirect('accounts:payment_page')

@transaction.atomic
def create_group_after_payment(request):
    data = request.session.get('pending_group_data')

    # 🔒 Session checks
    if not data:
        messages.error(request, "Session expired!")
        return redirect('accounts:group_signup')

    if not data.get('otp_verified'):
        messages.error(request, "OTP not verified!")
        return redirect('accounts:verify_group_otp')

    if not data.get('payment_done'):
        messages.error(request, "Payment not completed!")
        return redirect('accounts:payment_page')

    # 🛑 Duplicate protection
    if data.get('group_created'):
        return redirect('accounts:group_admin_dashboard')

    plan = get_object_or_404(SubscriptionPlan, id=data['plan_id'])

    # ----------------------------------
    # PLAN GROUP LIMIT CHECK
    # ----------------------------------
    existing_groups_count = GroupSubscription.objects.filter(
        group__owner__staffprofile__role='group_admin',
        plan=plan,
        is_active=True
    ).count()

    if plan.max_groups != 0 and existing_groups_count >= plan.max_groups:
        messages.error(
            request,
            f"You have reached your group limit for {plan.name} plan."
        )
        return redirect('accounts:group_admin_dashboard')

    # ----------------------------------
    # EMAIL DUPLICATE SAFETY
    # ----------------------------------
    if User.objects.filter(email=data['email']).exists():
        messages.error(request, "User already exists with this email.")
        return redirect('accounts:group_signup')

    # ----------------------------------
    # CREATE ADMIN USER
    # ----------------------------------
    username = f"group_{get_random_string(8)}"

    admin_user = User.objects.create_user(
        username=username,
        email=data['email'],
        password=data['password'],
        first_name=data['group_name']
    )

    # ----------------------------------
    # CREATE GROUP
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
    # STAFF PROFILE
    # ----------------------------------
    staff_profile = StaffProfile.objects.create(
        user=admin_user,
        group=group,
        phone=data['phone'],
        role='group_admin',
        is_subscribed=True
    )

    # ----------------------------------
    # PAYMENT ENTRY (ONLY PAID)
    # ----------------------------------
    if plan.price > 0:
        Payment.objects.create(
            collected_by=staff_profile,
            amount=plan.price,
            payment_method='razorpay',
            payment_status='success',
            group=group,
            subscription_plan=plan,
            paid_date=timezone.now().date(),
            # optional:
            # payment_id = request.session.get('razorpay_payment_id')
        )

    # ----------------------------------
    # SUBSCRIPTION
    # ----------------------------------
    GroupSubscription.objects.create(
        group=group,
        plan=plan,
        start_date=timezone.now().date(),
        end_date=timezone.now().date() + timezone.timedelta(days=plan.duration_days),
        is_active=True
    )

    # ----------------------------------
    # 🛑 MARK CREATED (prevent duplicate)
    # ----------------------------------
    data['group_created'] = True
    request.session['pending_group_data'] = data

    # ----------------------------------
    # 🧹 CLEAR SESSION (safe remove)
    # ----------------------------------
    request.session.pop('pending_group_data', None)

    messages.success(request, f"Group '{group.name}' created successfully!")

    # ----------------------------------
    # AUTO LOGIN
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


def get_user_kuris(request):
    """
    AJAX Endpoint: Returns role, admin status, and Kuris list for a given email/phone identifier.
    Supports Unified Selection:
    - Pure Group Admins: show_kuri_select = False (stays hidden)
    - Multi-Role Users (Admin + Member): show_kuri_select = True with 'Admin Portal' option + Member Kuris list
    - Pure Members / Collectors: show_kuri_select = True with Member Kuris list
    """
    identifier = request.GET.get('identifier', '').strip()
    kuris_list = []
    has_admin_role = False
    is_member = False
    is_collector = False

    if identifier:
        # 1. Check Staff Profile (Group Admin / Super Admin / Collector)
        staff = StaffProfile.objects.filter(
            Q(user__email=identifier) | Q(user__username=identifier) | Q(phone=identifier)
        ).first()

        if staff:
            if staff.role in ['group_admin', 'admin']:
                has_admin_role = True
                is_collector = True  # Group Admins can also manage collections

            elif staff.role == 'collector':
                is_collector = True
                groups = staff.assigned_chitti_groups.filter(is_active=True)
                for g in groups:
                    kuris_list.append({
                        'id': g.id,
                        'name': g.name,
                        'code': g.code
                    })

        # 2. Check Members
        members = Member.objects.filter(
            Q(email=identifier) | Q(phone=identifier) | Q(user__email=identifier) | Q(user__username=identifier)
        )

        if members.exists():
            is_member = True
            group_ids = set()
            for m in members:
                if m.assigned_chitti_group_id:
                    group_ids.add(m.assigned_chitti_group_id)
                for cm in m.chitti_memberships.all():
                    group_ids.add(cm.group_id)

            if group_ids:
                groups = ChittiGroup.objects.filter(id__in=group_ids, is_active=True)
                for g in groups:
                    if not any(k['id'] == g.id for k in kuris_list):
                        kuris_list.append({
                            'id': g.id,
                            'name': g.name,
                            'code': g.code
                        })

    # Show selector if multi-role or multiple Kuris exist
    show_kuri_select = False
    if has_admin_role and (len(kuris_list) > 0 or is_collector):
        show_kuri_select = True
    elif is_collector and (has_admin_role or len(kuris_list) > 0):
        show_kuri_select = True
    elif (is_member or is_collector) and (len(kuris_list) > 0):
        show_kuri_select = True

    return JsonResponse({
        'has_admin_role': has_admin_role,
        'has_collector_role': is_collector,
        'kuris': kuris_list,
        'show_kuri_select': show_kuri_select
    })


def login_view(request):
    if request.method == 'POST':
        identifier = request.POST.get('identifier', '').strip()
        password = request.POST.get('password', '')
        kuri_id = request.POST.get('kuri_id')

        # 🟢 CASE A: User explicitly selected "Admin Portal"
        if kuri_id == 'admin_portal':
            staff = StaffProfile.objects.filter(
                Q(user__email=identifier) | Q(user__username=identifier) | Q(phone=identifier),
                role__in=['group_admin', 'admin']
            ).first()

            if staff and staff.user and staff.user.check_password(password):
                if not staff.user.is_active:
                    messages.error(request, "Access denied. Your account has been disabled.")
                    return redirect('accounts:login')

                login(request, staff.user, backend='django.contrib.auth.backends.ModelBackend')
                if staff.role == 'admin':
                    return redirect('adminpanel:dashboard')
                else:
                    if not staff.group:
                        messages.info(request, "Welcome! Please set up your group details to get started.")
                        return redirect('accounts:create_group')
                    return redirect('accounts:group_admin_dashboard')
            else:
                messages.error(request, "Invalid Group Admin credentials.")
                return redirect('accounts:login')

        # 💵 CASE B: User explicitly selected "Collector Portal"
        elif kuri_id == 'collector_portal':
            staff = StaffProfile.objects.filter(
                Q(user__email=identifier) | Q(user__username=identifier) | Q(phone=identifier),
                role__in=['collector', 'group_admin', 'admin']
            ).first()

            if staff and staff.user and staff.user.check_password(password):
                if not staff.user.is_active:
                    messages.error(request, "Access denied. Your account has been disabled.")
                    return redirect('accounts:login')

                login(request, staff.user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('accounts:collector_dashboard')
            else:
                messages.error(request, "Invalid Collector credentials.")
                return redirect('accounts:login')

        # 🔵 CASE B: User explicitly selected a Member Kuri ID
        elif kuri_id and kuri_id != 'admin_portal':
            try:
                selected_group_id = int(kuri_id)
            except ValueError:
                selected_group_id = None

            if selected_group_id:
                cm = ChittiMember.objects.filter(
                    group_id=selected_group_id
                ).filter(
                    Q(member__email=identifier) | Q(member__phone=identifier) | Q(member__user__email=identifier) | Q(member__user__username=identifier)
                ).select_related('member__user').first()

                member = cm.member if cm else None

                if not member:
                    member = Member.objects.filter(
                        assigned_chitti_group_id=selected_group_id
                    ).filter(
                        Q(email=identifier) | Q(phone=identifier) | Q(user__email=identifier) | Q(user__username=identifier)
                    ).first()

                if member:
                    # Ensure member has a dedicated User object (isolated from staff user)
                    if not member.user:
                        username = f"mem_{member.id}_{member.phone or member.email or 'user'}"
                        new_user, _ = User.objects.get_or_create(username=username, defaults={'email': member.email or ''})
                        member.user = new_user
                        member.save(update_fields=['user'])

                    if member.user and member.user.check_password(password):
                        if not member.user.is_active:
                            messages.error(request, "Access denied. Your account has been disabled.")
                            return redirect('accounts:login')

                        login(request, member.user, backend='django.contrib.auth.backends.ModelBackend')
                        request.session['active_group_id'] = selected_group_id
                        return redirect('members:member_dashboard')
                    else:
                        messages.error(request, "Invalid password for selected Kuri account.")
                        return redirect('accounts:login')
                else:
                    messages.error(request, "No member record found for selected Kuri.")
                    return redirect('accounts:login')

        # 🟡 CASE C: Default Login (No Kuri selected)
        else:
            user = authenticate(request, username=identifier, password=password)

            if user is None:
                u = User.objects.filter(email=identifier).first()
                if u and u.check_password(password):
                    user = u

            if user is None:
                member = Member.objects.filter(phone=identifier).first()
                if member and member.user and member.user.check_password(password):
                    user = member.user

            if user is None:
                staff = StaffProfile.objects.filter(phone=identifier).first()
                if staff and staff.user and staff.user.check_password(password):
                    user = staff.user

            if user:
                if not user.is_active:
                    messages.error(request, "Access denied. Your account has been disabled.")
                    return redirect('accounts:login')

                login(request, user, backend='django.contrib.auth.backends.ModelBackend')

                if hasattr(user, 'staffprofile'):
                    profile = user.staffprofile
                    if profile.role == 'admin':
                        return redirect('adminpanel:dashboard')
                    elif profile.role == 'collector':
                        return redirect('accounts:collector_dashboard')
                    elif profile.role == 'group_admin':
                        if not profile.group:
                            messages.info(request, "Welcome! Please set up your group details to get started.")
                            return redirect('accounts:create_group')
                        return redirect('accounts:group_admin_dashboard')

                return redirect('members:member_dashboard')

        messages.error(request, "Invalid login details. Please check your credentials and try again.")
        return redirect('accounts:login')

    return render(request, 'accounts/login.html')


@login_required
def change_password(request):
    member = Member.objects.filter(
        Q(user=request.user) | Q(email=request.user.email) | Q(phone=request.user.username)
    ).first()

    if not member:
        if hasattr(request.user, 'staffprofile'):
            return redirect('accounts:group_admin_dashboard')
        return redirect('accounts:login')

    if not member.user:
        member.user = request.user
        member.save(update_fields=['user'])

    # Already changed password
    if not member.is_first_login:
        return redirect('members:member_dashboard')

    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not new_password or not confirm_password:
            messages.error(request, "Please enter both password fields.")
        elif len(new_password) < 4:
            messages.error(request, "Password must be at least 4 characters long.")
        elif new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
        else:
            user = request.user
            user.set_password(new_password)
            user.save()

            # KEEP SESSION ACTIVE
            update_session_auth_hash(request, user)

            member.is_first_login = False
            member.save()

            messages.success(request, "Password updated successfully! Welcome to SmartKuri.")
            return redirect('members:member_dashboard')

    return render(request, 'member/change_password.html', {'member': member})

# ------------------------
# LOGOUT
# ------------------------
def logout_view(request):
    logout(request)
    return redirect('accounts:login')

# ---------------------------------------
# PASSWORD RESET REQUEST
# ---------------------------------------
# PASSWORD RESET REQUEST (Unified Single Password Reset)
# ---------------------------------------
def password_reset_request(request):
    if request.method == "POST":
        identifier = request.POST.get("identifier", "").strip()

        if not identifier:
            messages.error(request, "Please enter your registered Email Address.")
            return redirect("accounts:password_reset")

        # 🔍 Find all User objects associated with this email
        target_users = []
        recipient_email = ""

        # 1. Staff profile matching
        staff = StaffProfile.objects.filter(
            Q(user__email__iexact=identifier) | Q(user__username__iexact=identifier)
        ).first()
        if staff and staff.user:
            target_users.append(staff.user)
            if staff.user.email:
                recipient_email = staff.user.email

        # 2. Member records matching
        members = Member.objects.filter(
            Q(email__iexact=identifier) | Q(user__email__iexact=identifier) | Q(user__username__iexact=identifier)
        )
        for m in members:
            if m.user and m.user not in target_users:
                target_users.append(m.user)
            if not recipient_email and m.email:
                recipient_email = m.email

        # 3. Direct Django User matching
        direct_users = User.objects.filter(
            Q(email__iexact=identifier) | Q(username__iexact=identifier)
        )
        for u in direct_users:
            if u not in target_users:
                target_users.append(u)
            if not recipient_email and u.email:
                recipient_email = u.email

        if not recipient_email and '@' in identifier:
            recipient_email = identifier

        if target_users:
            primary_user = target_users[0]
            otp = random.randint(100000, 999999)

            # Store user IDs list in session for synchronized password reset across all linked entities
            user_ids = [u.id for u in target_users]
            request.session['password_reset_user_ids'] = user_ids
            request.session['password_reset_user_id'] = primary_user.id
            request.session['password_reset_otp'] = otp
            request.session['otp_created_at'] = time.time()
            request.session['password_reset_recipient_email'] = recipient_email
            request.session['password_reset_target_name'] = "SmartKuri Account"

            send_professional_otp_email(
                recipient_email=recipient_email,
                otp_code=otp,
                action_type="reset",
                target_name="SmartKuri Account"
            )

            messages.success(request, f"OTP verification code sent to {recipient_email}. Please check your inbox.")
            return redirect("accounts:password_reset_verify")
        else:
            messages.error(request, "No user account found with this email address.")

    return render(request, "accounts/password_reset.html")


# ---------------------------------------
# RESEND PASSWORD RESET OTP
# ---------------------------------------
def resend_password_reset_otp(request):
    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, "Password reset session has expired. Please enter your email or phone again.")
        return redirect("accounts:password_reset")

    user = get_object_or_404(User, id=user_id)
    new_otp = random.randint(100000, 999999)
    request.session['password_reset_otp'] = new_otp
    request.session['otp_created_at'] = time.time()

    recipient_email = request.session.get('password_reset_recipient_email') or user.email

    send_professional_otp_email(
        recipient_email=recipient_email,
        otp_code=new_otp,
        action_type="reset",
        target_name="SmartKuri Account"
    )

    messages.success(request, f"New OTP sent to {recipient_email}! Please check your email.")
    return redirect("accounts:password_reset_verify")


# ---------------------------------------
# PASSWORD RESET CONFIRM
# ---------------------------------------
def password_reset_confirm(request):
    user_id = request.session.get('password_reset_user_id')
    if not user_id:
        messages.error(request, "Session expired. Please request a new OTP.")
        return redirect("accounts:password_reset")

    user = get_object_or_404(User, id=user_id)
    recipient_email = request.session.get('password_reset_recipient_email') or user.email

    if request.method == "POST":
        otp_entered = request.POST.get("otp", "").strip()
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")

        otp_saved = request.session.get('password_reset_otp')
        otp_time = request.session.get('otp_created_at')

        if not otp_saved or (time.time() - otp_time) > 300:
            messages.error(request, "OTP has expired. Please click 'Resend OTP' to get a new code.")
            return redirect("accounts:password_reset_verify")

        if str(otp_entered) != str(otp_saved):
            messages.error(request, "Invalid OTP code. Please enter the 6-digit code sent to your email.")
        elif not password1 or not password2:
            messages.error(request, "Please fill in both password fields.")
        elif len(password1) < 4:
            messages.error(request, "Password must be at least 4 characters long.")
        elif password1 != password2:
            messages.error(request, "Passwords do not match.")
        else:
            # Synchronize new password across all linked User records for this person
            user_ids = request.session.get('password_reset_user_ids', [user.id])
            users_to_update = User.objects.filter(id__in=user_ids)
            for u in users_to_update:
                u.set_password(password1)
                u.save()

            # Clean up all reset session data
            request.session.pop('password_reset_user_id', None)
            request.session.pop('password_reset_user_ids', None)
            request.session.pop('password_reset_kuri_id', None)
            request.session.pop('password_reset_otp', None)
            request.session.pop('otp_created_at', None)
            request.session.pop('password_reset_target_name', None)
            request.session.pop('password_reset_recipient_email', None)

            messages.success(request, "🎉 Password reset successful! You can now log in with your new password.")
            return redirect("accounts:login")

    context = {
        "user": user,
        "recipient_email": recipient_email,
        "target_name": "SmartKuri Unified Account"
    }
    return render(request, "accounts/password_reset_verify.html", context)




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
        received_by_admin=True,
        paid_date__gte=month_start
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= Total Collected =================
    total_received = Payment.objects.filter(
        group__owner=user,
        payment_status='success',
        received_by_admin=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= Context =================
    context = {
        'total_groups': total_groups,
        'active_groups': active_groups,
        'total_members': total_members,
        'this_month_collection': this_month_collection,
        'total_received': total_received,
        'groups': groups,
    }

    return render(request, 'chitti/group_admin_dashboard.html', context)




from datetime import date
from django.db.models import Sum

@login_required
@collector_required
def collector_dashboard(request):
    collector = request.user.staffprofile

    assigned_groups = collector.assigned_chitti_groups.filter(is_active=True)
    if not assigned_groups.exists() and collector.group:
        assigned_groups = ChittiGroup.objects.filter(id=collector.group_id, is_active=True)
    if not assigned_groups.exists() and collector.role in ['group_admin', 'admin']:
        active_id = request.session.get('active_group_id')
        if active_id:
            assigned_groups = ChittiGroup.objects.filter(id=active_id, is_active=True)
        else:
            assigned_groups = ChittiGroup.objects.filter(owner=request.user, is_active=True)

    # Recent 10 payments
    recent_payments = Payment.objects.filter(
        group__in=assigned_groups,
        payment_status='success'
    ).order_by('-paid_date', '-paid_time')[:10]

    # Today collection (non-cash or cash received by admin)
    today_collection = Payment.objects.filter(
        group__in=assigned_groups,
        paid_date=date.today(),
        payment_status='success'
    ).filter(
        ~Q(payment_method='cash') | Q(received_by_admin=True)
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Monthly collection
    monthly_collection = Payment.objects.filter(
        group__in=assigned_groups,
        paid_date__month=date.today().month,
        paid_date__year=date.today().year,
        payment_status='success'
    ).filter(
        ~Q(payment_method='cash') | Q(received_by_admin=True)
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Total collection
    total_collection = Payment.objects.filter(
        group__in=assigned_groups,
        payment_status='success'
    ).filter(
        ~Q(payment_method='cash') | Q(received_by_admin=True)
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Active members
    active_members = Member.objects.filter(
        Q(assigned_chitti_group__in=assigned_groups) | Q(chitti_memberships__group__in=assigned_groups)
    ).distinct().count()

    context = {
        'today_collection': today_collection,
        'monthly_collection': monthly_collection,
        'total_collection': total_collection,
        'active_members': active_members,
        'recent_payments': recent_payments,
    }

    return render(request, 'collector/collector_dashboard.html', context)




@login_required
def create_group_view(request):

    # 🔒 already has group
    if hasattr(request.user, 'staffprofile') and request.user.staffprofile.group:
        return redirect('accounts:group_admin_dashboard')

    plans = SubscriptionPlan.objects.filter(is_active=True)

    user_phone = request.user.staffprofile.phone if hasattr(request.user, 'staffprofile') else ""

    user_initial_data = {
        'full_name': request.user.get_full_name() or request.user.username,
        'email': request.user.email,
        'phone': user_phone,
    }

    if request.method == 'POST':
        try:
            # =========================
            # 🔥 PLAN
            # =========================
            plan_id = request.POST.get('subscription_plan')
            selected_plan = get_object_or_404(SubscriptionPlan, id=plan_id)

            # =========================
            # 🔥 DATES
            # =========================
            reg_date_str = request.POST.get('chitti_start_date')
            auction_date_str = request.POST.get('start_date')

            registration_date = datetime.strptime(reg_date_str, '%Y-%m-%d').date()
            auction_start_date = datetime.strptime(auction_date_str, '%Y-%m-%d').date()

            # ✅ validation
            if auction_start_date < registration_date:
                messages.error(request, "First auction date must be after registration date.")
                return redirect('chitti:create_group')

            with transaction.atomic():

                # =========================
                # 🔥 BASIC DATA
                # =========================
                monthly_amount = Decimal(request.POST.get('monthly_amount', '0'))
                duration_months = int(request.POST.get('duration_months', '0'))
                auctions_per_month = int(request.POST.get('auctions_per_month', 1))

                auction_type = request.POST.get('auction_type', 'monthly')
                auction_interval_months = request.POST.get('auction_interval_months') or None

                if auction_type == "interval":
                    auction_interval_months = int(auction_interval_months or 0)
                    if auction_interval_months <= 0:
                        raise ValueError("Invalid interval months")

                # =========================
                # 🔥 CREATE GROUP
                # =========================
                new_group = ChittiGroup.objects.create(
                    name=request.POST.get('name'),
                    phone=request.POST.get('phone'),
                    email=request.POST.get('email'),
                    owner=request.user,
                    monthly_amount=monthly_amount,
                    duration_months=duration_months,
                    total_amount=monthly_amount * duration_months,
                    auction_type=auction_type,
                    auctions_per_month=auctions_per_month,
                    auction_interval_months=auction_interval_months,
                    registration_start_date=registration_date,
                    start_date=auction_start_date
                )

                # =========================
                # 🔥 CREATE AUCTIONS (CORRECT LOGIC)
                # =========================

                # ✅ Single auction per month
                if auctions_per_month == 1:
                    new_group.create_auctions()

                # ✅ Multiple auctions per month
                else:
                    base_dates = []

                    # first date
                    base_dates.append(auction_start_date)

                    # other dates (date2, date3...)
                    for i in range(2, auctions_per_month + 1):
                        d_val = request.POST.get(f'date{i}')
                        if d_val:
                            base_dates.append(datetime.strptime(d_val, '%Y-%m-%d').date())

                    # 👉 call multi create
                    new_group.create_auctions_multi(base_dates)

                # =========================
                # 🔥 PROFILE UPDATE
                # =========================
                profile = request.user.staffprofile
                profile.group = new_group
                profile.save()

                # =========================
                # 🔥 SUBSCRIPTION
                # =========================
                subscription = GroupSubscription.objects.create(
                    group=new_group,
                    plan=selected_plan
                )
                subscription.activate(start_date=registration_date)

            messages.success(request, f"Group created! First auction on {auction_start_date}")
            return redirect('accounts:group_admin_dashboard')

        except ValueError:
            messages.error(request, "Invalid input or date format.")
        except Exception as e:
            messages.error(request, f"System Error: {str(e)}")

    return render(request, 'chitti/create_group.html', {
        'user_data': user_initial_data,
        'plans': plans
    })