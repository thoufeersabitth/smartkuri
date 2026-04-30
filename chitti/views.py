from builtins import ValueError
from collections import defaultdict
from decimal import Decimal
import json
from typing import Collection
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponseBadRequest, JsonResponse
from django.urls import reverse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from accounts.decorators import group_admin_required
from accounts.forms import CashCollectorCreateForm, CashCollectorEditForm
from accounts.models import StaffProfile
from django.db import transaction
from datetime import datetime
from django.views.decorators.http import require_POST
from chitti.forms import AuctionForm
import random
from dateutil.relativedelta import relativedelta
from subscriptions.utils import can_create_group, get_effective_subscription
from datetime import date
from payments.models import Payment 
from django.db.models import Sum
from datetime import timedelta



from .models import Auction, ChittiGroup, ChittiMember
from subscriptions.models import GroupSubscription, SubscriptionPlan

import razorpay
from django.conf import settings


# -----------------------------
# Currency Helper
# -----------------------------
def currency(amount):
    try:
        return f"₹{float(amount):,.2f}"
    except (ValueError, TypeError):
        return "₹0.00"


# -----------------------------
# Group  List




@login_required
def group_management(request):

    groups = ChittiGroup.objects.filter(owner=request.user).prefetch_related('auctions')

    if not groups.exists():
        return redirect('chitti:create_group')

    updated_groups = []

    for group in groups:

        # ✅ BASE START
        base_start = group.registration_start_date or group.start_date

        # ✅ FIX END DATE
        end_date = None
        if base_start and group.duration_months:
            end_date = base_start + relativedelta(months=group.duration_months) - relativedelta(days=1)

        # ✅ EXPIRED CHECK
        is_expired = end_date and date.today() > end_date

        # ✅ GET FIRST AUCTION (CORRECT)
        first_auction = group.auctions.all().order_by('auction_date').first()

        # ✅ ATTACH VALUES
        group.end_date_calculated = end_date
        group.is_expired = is_expired
        group.first_auction_date = first_auction.auction_date if first_auction else None

        # ✅ DAYS LEFT
        if group.start_date:
            group.days_until_first_auction = (group.start_date - date.today()).days

        updated_groups.append(group)

    return render(request, 'chitti/group_management.html', {
        'groups': updated_groups
    })
@login_required
@transaction.atomic
def add_group(request):
    user = request.user

    # 🔒 Only group_admin allowed
    if not hasattr(user, 'staffprofile') or user.staffprofile.role != 'group_admin':
        messages.error(request, "Only group admins can create groups.")
        return redirect('chitti:group_management')

    if request.method == "POST":
        try:
            # =============================
            # 📥 BASIC INPUTS
            # =============================
            name = request.POST.get('name', '').strip()
            monthly_amount = Decimal(request.POST.get('monthly_amount', '0'))
            duration_months = int(request.POST.get('duration_months', '0'))

            auctions_per_month = int(request.POST.get('auctions_per_month', '1'))
            auction_type = request.POST.get('auction_type', 'monthly')
            auction_interval_months = request.POST.get('auction_interval_months')

            # =============================
            # 🔁 INTERVAL VALIDATION
            # =============================
            if auction_type == "interval":
                auction_interval_months = int(auction_interval_months or 0)
                if auction_interval_months <= 0:
                    raise ValueError("Invalid interval months")
            else:
                auction_interval_months = None

            # =============================
            # 📅 DATE PARSING
            # =============================
            date_input = request.POST.get('start_date')

            try:
                start_date = datetime.strptime(date_input, "%d-%m-%Y").date()
            except ValueError:
                start_date = datetime.strptime(date_input, "%Y-%m-%d").date()

            # =============================
            # ✅ BASIC VALIDATION
            # =============================
            if not name or monthly_amount <= 0 or duration_months <= 0:
                raise ValueError("Invalid basic input")

            # =============================
            # 🔥 MANUAL AUCTION DATES
            # =============================
            base_dates = []

            for i in range(1, auctions_per_month + 1):
                d = request.POST.get(f"auction_date_{i}")

                if not d:
                    raise ValueError(f"Auction date {i} missing")

                auction_date = datetime.strptime(d, "%Y-%m-%d").date()

                if auction_date < start_date:
                    raise ValueError(f"Auction date {i} must be after start date")

                base_dates.append(auction_date)

            # ❌ Duplicate check
            if len(base_dates) != len(set(base_dates)):
                raise ValueError("Duplicate auction dates not allowed")

            # ❌ Order check
            if base_dates != sorted(base_dates):
                raise ValueError("Auction dates must be ascending")

        except Exception as e:
            messages.error(request, f"Invalid input: {str(e)}")
            return redirect('chitti:add_group')

        # =============================
        # 🔍 MAIN GROUP CHECK
        # =============================
        main_group = ChittiGroup.objects.filter(
            owner=user,
            parent_group__isnull=True
        ).first()

        # =============================
        # 🔥 CREATE GROUP FUNCTION
        # =============================
        def create_group(parent=None):

            group = ChittiGroup.objects.create(
                owner=user,
                parent_group=parent,
                name=name,
                monthly_amount=monthly_amount,
                duration_months=duration_months,
                total_amount=monthly_amount * duration_months,

                auction_type=auction_type,
                auctions_per_month=auctions_per_month,
                auction_interval_months=auction_interval_months,

                registration_start_date=start_date,
                start_date=start_date
            )

            # =============================
            # 🔥 FIXED AUCTION CREATION
            # =============================
            if auctions_per_month == 1:
                group.create_auctions()
            else:
                group.create_auctions(base_dates=base_dates)

            return group

        # =============================
        # 🟢 MAIN GROUP
        # =============================
        if not main_group:
            group = create_group()

            profile = user.staffprofile
            profile.group = group
            profile.save()

            messages.success(request, "Main group created successfully ✅")
            return redirect('chitti:group_management')

        # =============================
        # 🔵 SUB GROUP
        # =============================
        subscription = get_effective_subscription(main_group)

        if not subscription:
            messages.error(request, "Subscription inactive.")
            return redirect('chitti:group_management')

        if not can_create_group(user):
            messages.error(
                request,
                f"Limit reached for {subscription.plan.name}"
            )
            return redirect('chitti:group_management')

        create_group(parent=main_group)

        messages.success(request, f"Sub-group '{name}' created successfully ✅")
        return redirect('chitti:group_management')

    # =============================
    # 📊 GET REQUEST
    # =============================
    main_group = ChittiGroup.objects.filter(
        owner=user,
        parent_group__isnull=True
    ).first()

    subscription = get_effective_subscription(main_group) if main_group else None
    existing_count = ChittiGroup.objects.filter(owner=user).count()

    remaining_groups = 0
    if subscription:
        remaining_groups = max(
            subscription.plan.max_groups - existing_count,
            0
        )

    return render(request, "chitti/add_group.html", {
        "subscription": subscription,
        "plan": subscription.plan if subscription else None,
        "remaining_groups": remaining_groups,
    })


def view_group(request, group_id):

    # 1. Fetch Group
    group = get_object_or_404(
        ChittiGroup, 
        id=group_id, 
        owner=request.user
    )

    # 2. Members & Auctions
    members = group.chitti_members.all()
    total_members = members.count()

    auctions = group.auctions.select_related('winner').all().order_by('month_no', 'auction_no')

    # 3. Financial Tracking
    payments = Payment.objects.filter(group=group, payment_status='success')
    
    total_collected = payments.filter(received_by_admin=True).aggregate(
        total=Sum('amount'))['total'] or 0
        
    pending_total = payments.filter(received_by_admin=False).aggregate(
        total=Sum('amount'))['total'] or 0

    # 4. Pot Logic
    monthly_pot = group.monthly_amount * total_members

    # 5. Progress Tracking
    completed_auctions = auctions.filter(winner__isnull=False)
    completed_count = completed_auctions.count()

    completed_months = completed_auctions.values('month_no').distinct().count()
    
    current_month = completed_months + 1
    remaining_months = max(0, (group.duration_months or 0) - completed_months)

    # 6. Prize Calculation
    for auction in auctions:
        discount = auction.bid_amount or 0
        auction.calculated_prize = monthly_pot - discount

    # ✅ FIXED LAST AUCTION (SAFE)
    last_auction = completed_auctions.order_by('auction_date').last()

    last_winner = last_auction.winner if last_auction else None
    last_discount = last_auction.bid_amount if last_auction else 0
    last_prize = (monthly_pot - last_discount) if last_auction else 0

    # 8. Date Logic
    base_date = group.registration_start_date or group.start_date
    
    end_date = None
    is_expired = False
    
    if base_date and group.duration_months:
        # ✅ FIXED END DATE
        end_date = base_date + relativedelta(months=group.duration_months) - relativedelta(days=1)
        is_expired = date.today() > end_date

    # 9. Efficiency
    expected_total = group.monthly_amount * total_members * completed_months
    efficiency = 0
    if expected_total > 0:
        efficiency = (total_collected / expected_total) * 100

    # 10. Context
    context = {
        'group': group,
        'members': members,
        'auctions': auctions,

        'total_members': total_members,
        'monthly_pot': monthly_pot,
        'current_month': current_month,
        'completed_months': completed_months,
        'remaining_months': remaining_months,

        'last_winner': last_winner,
        'last_prize': last_prize,
        'last_discount': last_discount,

        'total_collected': total_collected,
        'pending_total': pending_total,  
        'collection_efficiency': round(efficiency, 1),

        'end_date': end_date,
        'is_expired': is_expired,
        'today': date.today(),
    }

    return render(request, 'chitti/view_group.html', context)
@login_required
def subscribe_group(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, parent_group__isnull=True, owner=request.user)

    if hasattr(group, 'subscription'):
        messages.info(request, "This group already has a subscription.")
        return redirect('chitti:group_management')

    plan = SubscriptionPlan.objects.filter(is_active=True).first()
    if not plan:
        messages.error(request, "No active subscription plan available.")
        return redirect('chitti:group_management')

    GroupSubscription.objects.create(group=group, plan=plan, is_active=True)
    messages.success(request, f"Subscription activated for {group.name}")
    return redirect('chitti:group_management')

# -----------------------------
# Edit Group
# -----------------------------
# ==================================================
# EDIT GROUP
# ==================================================
@login_required
def edit_group(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, owner=request.user)

    if request.method == 'POST':
        try:
            group.name = request.POST.get('name', group.name)
            group.monthly_amount = Decimal(request.POST.get('monthly_amount', group.monthly_amount))
            group.duration_months = int(request.POST.get('duration_months', group.duration_months))
            group.collections_per_month = int(request.POST.get('collections_per_month', group.collections_per_month))
            group.auctions_per_month = int(request.POST.get('auctions_per_month', group.auctions_per_month))
            start_date = request.POST.get('start_date')
            if start_date:
                try:
                    group.start_date = datetime.strptime(start_date, "%d-%m-%Y").date()
                except ValueError:
                    group.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()

            # Auto calculate total
            group.total_amount = group.monthly_amount * group.duration_months

            group.save()
            messages.success(request, "Group updated successfully!")
            return redirect('chitti:group_management')

        except Exception:
            messages.error(request, "Invalid input data!")

    context = {"group": group}
    return render(request, 'chitti/edit_group.html', context)
# -----------------------------
# Close Group
# -----------------------------
@login_required
def close_group(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, owner=request.user)
    today = timezone.now().date()

    if today < group.end_date:
        months = (today.year - group.start_date.year) * 12 + (today.month - group.start_date.month) + 1
        group.duration_months = max(1, months)
        group.is_active = False
        group.save()
        messages.success(request, f"Group '{group.name}' closed successfully.")

    return redirect('chitti:group_management')


# -----------------------------
# Renew Subscription (Razorpay)
# -----------------------------
@login_required
def renew_subscription(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, owner=request.user)
    plan = SubscriptionPlan.objects.filter(is_active=True).first()

    if not plan:
        messages.error(request, "No active subscription plan available.")
        return redirect('chitti:group_management')

    # Initialize Razorpay client
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    amount_paise = int(plan.price * 100)  # Convert to paise

    # Create Razorpay order
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "payment_capture": 1
    })

    # Get or create subscription record
    subscription, _ = GroupSubscription.objects.get_or_create(
        group=group,
        defaults={'plan': plan, 'is_active': False}
    )

    subscription.plan = plan
    subscription.razorpay_order_id = order["id"]
    subscription.is_active = False  # activate after payment
    subscription.save()

    # Save in session for callback
    request.session['renew_group_id'] = group.id
    request.session['razorpay_order_id'] = order['id']

    return render(request, 'chitti/razorpay_checkout.html', {
        'group': group,
        'plan': plan,
        'order_id': order["id"],
        'amount': amount_paise,
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'callback_url': request.build_absolute_uri(reverse('chitti:razorpay_callback'))
    })


# -----------------------------
# Razorpay Callback
# -----------------------------
@csrf_exempt
def razorpay_callback(request):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request")

    payment_id = request.POST.get("razorpay_payment_id")
    order_id = request.POST.get("razorpay_order_id")
    signature = request.POST.get("razorpay_signature")

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature
        })
    except razorpay.errors.SignatureVerificationError:
        return HttpResponseBadRequest("Payment verification failed")

    # Fetch group from session
    group_id = request.session.get('renew_group_id')
    if not group_id:
        return HttpResponseBadRequest("Group not found in session")

    group = get_object_or_404(ChittiGroup, id=group_id)
    subscription = getattr(group, 'subscription', None)
    if not subscription:
        return HttpResponseBadRequest("Subscription not found")

    # Activate subscription
    subscription.activate()
    messages.success(request, f"Subscription renewed successfully for group '{group.name}'!")

    # Clear session
    request.session.pop('renew_group_id', None)
    request.session.pop('razorpay_order_id', None)

    return redirect('chitti:group_management')





# -------------------------------
# 1️⃣ Create Cash Collector
# -------------------------------
# 1️⃣ Create Cash Collector
@group_admin_required
def create_cash_collector(request):
    admin_user = request.user

    if request.method == "POST":
        form = CashCollectorCreateForm(request.POST, admin_user=admin_user)
        if form.is_valid():
            username = form.cleaned_data['username']
            email = form.cleaned_data['email']
            phone = form.cleaned_data['phone']
            password = form.cleaned_data['password']
            group = form.cleaned_data['group']

            # 🔥 NEW CHECK: Group already has collector?
            if group.collector:
                messages.error(
                    request,
                    f"Collector already created for group '{group.name}'."
                )
                return redirect('chitti:create_cash_collector')

            # 🔹 Create Django User
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # 🔹 Create StaffProfile
            collector = StaffProfile.objects.create(
                user=user,
                phone=phone,
                role='collector'
            )

            # 🔹 Assign collector to ChittiGroup
            group.collector = collector
            group.save()

            messages.success(
                request,
                f"Cash Collector '{username}' created in group '{group.name}'!"
            )
            return redirect('chitti:cash_collector_list')

        else:
            messages.error(request, "Please fix the errors below.")

    else:
        form = CashCollectorCreateForm(admin_user=admin_user)

    return render(
        request,
        'chitti/create_cash_collector.html',
        {'form': form}
    )

# -------------------------------
# 2️⃣ List Cash Collectors
# -------------------------------
@group_admin_required
def cash_collector_list(request):
    admin_user = request.user

    # Get all groups owned by this admin
    groups = ChittiGroup.objects.filter(owner=admin_user)

    # Get all collectors assigned to these groups
    collectors = StaffProfile.objects.filter(
        role='collector',
        assigned_chitti_groups__in=groups  # assigned_chitti_groups is related_name in ChittiGroup.collector
    ).select_related('user').distinct()

    return render(
        request,
        'chitti/cash_collector_list.html',
        {'collectors': collectors}
    )
#@group_admin_required
def edit_cash_collector(request, pk):
    collector_profile = get_object_or_404(
        StaffProfile,
        pk=pk,
        role='collector'
    )

    user = collector_profile.user

    if request.method == "POST":
        form = CashCollectorEditForm(request.POST, admin_user=request.user)

        if form.is_valid():
            user.email = form.cleaned_data['email']
            user.save()

            collector_profile.phone = form.cleaned_data['phone']
            collector_profile.group = form.cleaned_data['group']
            collector_profile.save()

            messages.success(request, "Cash Collector updated successfully!")
            return redirect('chitti:cash_collector_list')
    else:
        form = CashCollectorEditForm(
            initial={
                'username': user.username,
                'email': user.email,
                'phone': collector_profile.phone,
                'group': collector_profile.group,
            },
            admin_user=request.user
        )

    return render(request, 'chitti/create_cash_collector.html', {
        'form': form,
        'edit': True
    })

# -------------------------------
@group_admin_required
def delete_cash_collector(request, pk):

    collector_profile = get_object_or_404(
        StaffProfile,
        pk=pk,
        role='collector',
        assigned_chitti_groups__owner=request.user
    )

    username = collector_profile.user.username

    # Remove collector from all groups owned by this admin
    ChittiGroup.objects.filter(
        collector=collector_profile,
        owner=request.user
    ).update(collector=None)

    # Delete user (StaffProfile auto deletes if OneToOne)
    collector_profile.user.delete()

    messages.success(
        request,
        f"Cash Collector '{username}' deleted!"
    )

    return redirect('chitti:cash_collector_list')


# ==================================================
# Auction List
# ==================================================
@login_required
def auction_list_view(request):
    groups = ChittiGroup.objects.filter(owner=request.user)
    return render(request, 'chitti/auction_list.html', {
        'groups': groups
    })


from dateutil.relativedelta import relativedelta

from dateutil.relativedelta import relativedelta

@login_required
def auction_list_group_view(request, group_id):
    group = get_object_or_404(
        ChittiGroup,
        id=group_id,
        owner=request.user
    )

    months = []

    auction_type = group.auction_type

    # ✅ correct field name
    interval_months = int(getattr(group, "auction_interval_months", 1) or 1)

    auctions = group.auctions.all()

    for i in range(1, group.duration_months + 1):

        month_date = group.start_date + relativedelta(months=i-1)

        month_data = {
            'month_no': i,
            'auctions': [],
            'is_auction_month': True,
            'auto_date': None
        }

        # 🔴 INTERVAL LOGIC
        if auction_type == "interval":
            if (i - 1) % interval_months != 0:
                month_data['is_auction_month'] = False
                months.append(month_data)
                continue

        # 🟢 GET AUCTIONS
        month_auctions = auctions.filter(month_no=i).order_by('auction_no')

        if month_auctions.exists():
            month_data['auctions'] = month_auctions
        else:
            # 🔥 auto date only for valid auction months
            month_data['auto_date'] = month_date

        months.append(month_data)

    return render(request, 'chitti/auction_list_group.html', {
        'group': group,
        'months': months
    })


# ==================================================
# Add Auction
# ==================================================
@login_required
def add_auction(request):

    if request.method == "POST":

        group_id = request.POST.get("group_id")
        auction_date_str = request.POST.get("auction_date")

        # 🔹 Required check
        if not group_id or not auction_date_str:
            messages.error(request, "Group and Auction Date are required.")
            return redirect("chitti:add_auction")

        # 🔹 Convert date
        try:
            auction_date = datetime.strptime(
                auction_date_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect("chitti:add_auction")

        # 🔹 Get group
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 🔹 Check auction date inside duration
        group_end_date = group.start_date + relativedelta(
            months=group.duration_months
        )

        if auction_date < group.start_date or auction_date >= group_end_date:
            messages.error(request, "Auction date exceeds group duration period.")
            return redirect("chitti:add_auction")

        # 🔥 Calculate month_no correctly
        month_no = (
            (auction_date.year - group.start_date.year) * 12
            + (auction_date.month - group.start_date.month)
            + 1
        )

        # 🔹 Count auctions in this month
        monthly_auction_count = group.auctions.filter(
            month_no=month_no
        ).count()

        # 🔥 Limit based on group setting
        if monthly_auction_count >= group.auctions_per_month:
            messages.error(
                request,
                f"Only {group.auctions_per_month} auctions allowed for this month."
            )
            return redirect("chitti:add_auction")

        # 🔹 Total auction limit check
        total_auctions = group.auctions.count()

        if total_auctions >= group.total_auctions:
            messages.error(request, "Auction limit reached for this group.")
            return redirect("chitti:add_auction")

        # 🔥 Assign auction_no dynamically
        auction_no = monthly_auction_count + 1

        # ✅ Create Auction
        Auction.objects.create(
            group=group,
            auction_date=auction_date,
            month_no=month_no,
            auction_no=auction_no
        )

        messages.success(
            request,
            f"Auction created successfully (Month {month_no} - Auction {auction_no})"
        )

        return redirect("chitti:auction_list")

    # GET
    groups = ChittiGroup.objects.filter(owner=request.user)

    return render(request, "chitti/add_auction.html", {
        "groups": groups
    })

# ==================================================
# Spin Page: Shows the wheel
# ==================================================
# ==================================================
# Spin page (GET)
# ==================================================

@login_required
def auction_spin_view(request, auction_id):

    # =========================
    # 🔍 GET AUCTION
    # =========================
    auction = get_object_or_404(
        Auction,
        id=auction_id,
        group__owner=request.user
    )

    # =========================
    # 🚫 BLOCK IF CLOSED
    # =========================
    if auction.is_closed:
        messages.warning(request, "⚠️ This auction is already completed.")
        return redirect('chitti:auction_detail', auction_id=auction.id)

    # =========================
    # 📅 DATE CHECK (STRICT)
    # =========================
    today = date.today()

    if auction.auction_date != today:
        if auction.auction_date < today:
            messages.error(
                request,
                f"⛔ This auction date ({auction.auction_date}) has already passed."
            )
        else:
            messages.error(
                request,
                f"⏳ You can only spin this auction on {auction.auction_date}."
            )

        return redirect('chitti:auction_detail', auction_id=auction.id)

    # =========================
    # 👥 ALL MEMBERS
    # =========================
    all_members = ChittiMember.objects.filter(group=auction.group)

    # =========================
    # 🏆 PREVIOUS WINNERS
    # =========================
    previous_winners = Auction.objects.filter(
        group=auction.group,
        winner__isnull=False
    ).exclude(id=auction.id).values_list('winner_id', flat=True)

    # =========================
    # ✅ ELIGIBLE MEMBERS
    # =========================
    eligible_members = all_members.exclude(id__in=previous_winners)

    # =========================
    # 🚫 NO MEMBERS CHECK
    # =========================
    if not eligible_members.exists():
        messages.warning(
            request,
            "⚠️ No eligible members available for this auction."
        )
        return redirect('chitti:auction_detail', auction_id=auction.id)

    # =========================
    # 📦 CONTEXT
    # =========================
    context = {
        'auction': auction,
        'members': eligible_members,
        'no_members': False,
        'current_auction_month': auction.month_no or 1,
        'group_duration': auction.group.duration_months,
    }

    return render(request, 'chitti/auction_spin.html', context)





@login_required
@require_POST
def assign_winner_ajax(request, auction_id):
    auction = get_object_or_404(
        Auction,
        id=auction_id,
        group__owner=request.user
    )

    if auction.is_closed:
        return JsonResponse({'success': False, 'error': 'Auction already closed'}, status=400)

    member_id = request.POST.get('member_id')
    
    # 🔹 Get currently eligible members
    all_members = ChittiMember.objects.filter(group=auction.group)
    previous_winners = Auction.objects.filter(
        group=auction.group, 
        winner__isnull=False
    ).values_list('winner_id', flat=True)
    
    eligible_members = all_members.exclude(id__in=previous_winners)

    if not eligible_members.exists():
        return JsonResponse({'success': False, 'error': 'No eligible members left'}, status=400)

    # 🔹 Winner Selection
    if member_id:
        try:
            # Ensure the selected member is actually eligible
            winner = eligible_members.get(id=member_id)
        except ChittiMember.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Member is already a winner or invalid'}, status=400)
    else:
        # Fallback to random if JS fails to send ID
        import random
        winner = random.choice(list(eligible_members))

    # ✅ Assign and Save
    auction.assign_winner(winner, bid_amount=0)
    auction.is_closed = True
    auction.save()

    return JsonResponse({
        'success': True,
        'winner_id': winner.id,
        'winner_name': winner.member.name,
    })

# ==================================================
# Auction Detail
# ==================================================
@login_required
def auction_detail_view(request, auction_id):
    auction = get_object_or_404(
        Auction.objects.select_related(
            'group', 'winner', 'winner__member'
        ),
        id=auction_id,
        group__owner=request.user
    )

    # total_chitti_amount maatti total_amount aakki
    context = {
        'auction': auction,
        'group': auction.group,
        'total_pool': auction.group.total_amount, 
    }

    return render(request, 'chitti/auction_detail.html', context)


@login_required
@require_POST
def assign_all_winners_ajax(request, auction_id):
    # 1. Get the initial auction to identify the group and owner
    initial_auction = get_object_or_404(
        Auction.objects.select_related('group'), 
        id=auction_id, 
        group__owner=request.user
    )
    group = initial_auction.group

    try:
        data = json.loads(request.body)
        winners_list = data.get('winners', [])

        if not winners_list:
            return JsonResponse({'success': False, 'error': 'No winner data received'}, status=400)

        with transaction.atomic():
            for item in winners_list:
                month_num = int(item.get('month'))
                member_id = item.get('id')
                
                # Get the member object
                winner_member = ChittiMember.objects.get(id=member_id, group=group)

                # 2. Get or Create the auction record for that specific month
                # Note: We use 'month_no' as per your model
                auction, created = Auction.objects.get_or_create(
                    group=group, 
                    month_no=month_num,
                    auction_no=1, # Defaulting to 1 as per your model
                    defaults={
                        # Calculate a future date if creating a new month record
                        'auction_date': initial_auction.auction_date + timedelta(days=30 * (month_num - initial_auction.month_no)),
                        'selection_type': 'manual', 
                    }
                )

                # 3. Assign the winner using your model's method
                # This method handles self.winner assignment and self.save()
                if not auction.is_closed:
                    auction.assign_winner(winner_member, bid_amount=0)

        return JsonResponse({'success': True})

    except ChittiMember.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Member not found'}, status=404)
    except ValueError as e:
        # This catches "Member already won!" or "Auction already closed!" from your model
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': "Unexpected error: " + str(e)}, status=500)


def edit_auction_dates(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id)

    if request.method == "POST":
        auction_id = request.POST.get('auction_id')
        month_no = request.POST.get('month_no')
        new_date = request.POST.get('new_date')

        if not new_date:
            messages.error(request, "Please select a valid date.")
            return redirect('chitti:view_group', group_id=group.id)

        # CASE 1: Updating an existing Auction
        if auction_id:
            auction = get_object_or_404(Auction, id=auction_id, group=group)
            if not auction.winner:
                auction.auction_date = new_date
                auction.save()
                messages.success(request, f"Month {auction.month_no} date updated to {new_date}.")
            else:
                messages.error(request, "Cannot edit a completed auction.")

        # CASE 2: Creating a new entry (if it doesn't exist yet)
        elif month_no:
            # Prevent creating duplicate months for the same group
            if Auction.objects.filter(group=group, month_no=month_no).exists():
                messages.error(request, f"Month {month_no} already exists. Please edit the existing date.")
            else:
                Auction.objects.create(
                    group=group,
                    auction_date=new_date,
                    month_no=month_no
                )
                messages.success(request, f"Auction scheduled for Month {month_no}.")

    return redirect('chitti:view_group', group_id=group.id)
# -----------------------------


from django.db.models import Sum, Count
from collections import defaultdict
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required

from chitti.models import ChittiGroup
from payments.models import Payment


# --------- ADMIN PAYMENT LIST ----------
@login_required
def admin_pending_payments(request):

    staff = request.user.staffprofile

    if staff.role == 'admin':
        groups = ChittiGroup.objects.all()

    elif staff.role == 'group_admin':
        main_groups = ChittiGroup.objects.filter(owner=staff.user)
        sub_groups = ChittiGroup.objects.filter(parent_group__in=main_groups)
        groups = (main_groups | sub_groups).distinct()

    else:
        messages.error(request, "You are not authorized")
        return redirect('home')

    payments = Payment.objects.filter(
        payment_status='success',
        group__in=groups,
        collected_by__isnull=False,
        collected_by__role='collector',
        sent_to_admin=True
    ).select_related('member', 'group', 'collected_by') \
     .order_by('-paid_date', '-id')

    payments_by_group = defaultdict(list)

    for payment in payments:
        payments_by_group[payment.group].append(payment)

    group_list = []

    for group, group_payments in payments_by_group.items():

        pending = [p for p in group_payments if p.admin_status == 'pending']
        approved = [p for p in group_payments if p.admin_status == 'approved']
        rejected = [p for p in group_payments if p.admin_status == 'rejected']

        group_list.append({
            'group': group,
            'pending_payments': pending,
            'approved_payments': approved,
            'rejected_payments': rejected,   # 🔥 ADDED

            'total_pending': sum(p.amount for p in pending),
            'total_approved': sum(p.amount for p in approved),
            'total_rejected': sum(p.amount for p in rejected),  # 🔥 ADDED

            'count_pending': len(pending),
            'count_approved': len(approved),
            'count_rejected': len(rejected),  # 🔥 ADDED
        })

    return render(request, 'chitti/admin_pending_payments.html', {
        'group_list': group_list
    })


# --------- GROUP DETAILS ----------
@login_required
def group_payment_details(request, group_id):

    staff = request.user.staffprofile

    if staff.role == 'admin':
        group = get_object_or_404(ChittiGroup, id=group_id)

    elif staff.role == 'group_admin':
        group = get_object_or_404(ChittiGroup, id=group_id, owner=staff.user)

    else:
        messages.error(request, "Not allowed")
        return redirect('home')

    payments = Payment.objects.filter(
        group=group,
        payment_status='success',
        collected_by__isnull=False,
        collected_by__role='collector',
        sent_to_admin=True
    ).select_related('member', 'collected_by__user') \
     .order_by('-paid_date')

    return render(request, 'chitti/group_payment_details.html', {
        'group': group,
        'payments': payments
    })


# --------- APPROVE ----------
@login_required
def admin_approve_payment(request, payment_id):

    if request.method != "POST":
        return redirect('chitti:admin_pending_payments')

    payment = get_object_or_404(
        Payment,
        id=payment_id,
        sent_to_admin=True
    )

    if payment.admin_status != 'approved':
        payment.admin_status = 'approved'
        payment.save()
        payment.allocate_payment()

        messages.success(request, f"₹{payment.amount} approved & added")

    return redirect('chitti:admin_pending_payments')


# --------- REJECT ----------
@login_required
def admin_reject_payment(request, payment_id):

    if request.method != "POST":
        return redirect('chitti:admin_pending_payments')

    payment = get_object_or_404(
        Payment,
        id=payment_id,
        sent_to_admin=True
    )

    if payment.admin_status != 'rejected':
        payment.admin_status = 'rejected'

        # 🔥 IMPORTANT ADD (collector notification support)
        payment.collector_request_status = 'rejected' if hasattr(payment, 'collector_request_status') else None

        payment.save()

        messages.warning(request, f"₹{payment.amount} rejected")

    return redirect('chitti:admin_pending_payments')


# --------- GROUP APPROVE ----------
@login_required
def admin_approve_payment_group(request, group_id):

    if request.method != "POST":
        return redirect('chitti:admin_pending_payments')

    payments = Payment.objects.filter(
        group_id=group_id,
        payment_status='success',
        admin_status='pending',
        sent_to_admin=True
    )

    total = payments.aggregate(total=Sum('amount'))['total'] or 0

    if total > 0:

        for p in payments:
            p.admin_status = 'approved'
            p.save()
            p.allocate_payment()

        messages.success(request, f"All ₹{total} approved & added")

    return redirect('chitti:admin_pending_payments')


# --------- GROUP REJECT ----------
@login_required
def admin_reject_payment_group(request, group_id):

    if request.method != "POST":
        return redirect('chitti:admin_pending_payments')

    payments = Payment.objects.filter(
        group_id=group_id,
        payment_status='success',
        admin_status='pending',
        sent_to_admin=True
    )

    total = payments.aggregate(total=Sum('amount'))['total'] or 0

    if total > 0:
        payments.update(admin_status='rejected')

    return redirect('chitti:admin_pending_payments')


# --------- NOTIFICATIONS ----------
def group_admin_notifications(request):

    if request.user.is_authenticated and request.user.is_staff:

        pending = Payment.objects.filter(
            sent_to_admin=True,
            admin_status='pending'
        )

        rejected = Payment.objects.filter(
            admin_status='rejected'
        )

        return {
            'pending_groups': pending,
            'rejected_count': rejected.count(),
            'total_pending_count': pending.count()
        }

    return {
        'pending_groups': [],
        'rejected_count': 0,
        'total_pending_count': 0
    }

def clear_all_notifications(request):
    # Admin ippo kandu kondirikkunna ella pending notifications-um 'seen' aayi mark cheyyunnu
    Payment.objects.filter(
        sent_to_admin=True,
        admin_status='pending',
        is_seen=False
    ).update(is_seen=True)
    
    return redirect(request.META.get('HTTP_REFERER', '/'))