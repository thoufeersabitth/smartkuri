from builtins import ValueError
from collections import defaultdict
from decimal import Decimal
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
    groups = ChittiGroup.objects.filter(owner=request.user)

    if not groups.exists():
        return redirect('chitti:add_group')

    updated_groups = []

    for group in groups:

        # ✅ CALCULATE END DATE
        if group.start_date and group.duration_months:
            end_date = group.start_date + relativedelta(months=group.duration_months)
        else:
            end_date = None

        # ✅ CHECK EXPIRED
        is_expired = False
        if end_date and date.today() > end_date:
            is_expired = True

        # ✅ TEMP VALUES (no DB save)
        group.end_date_calculated = end_date
        group.is_expired = is_expired

        updated_groups.append(group)

    return render(request, 'chitti/group_management.html', {
        'groups': updated_groups
    })


@login_required
@transaction.atomic
def add_group(request):
    user = request.user

    # Only group_admin allowed
    if not hasattr(user, 'staffprofile') or user.staffprofile.role != 'group_admin':
        messages.error(request, "Only group admins can create groups.")
        return redirect('chitti:group_management')

    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            monthly_amount = Decimal(request.POST.get('monthly_amount', '0'))
            duration_months = int(request.POST.get('duration_months', '0'))

            collections_per_month = int(request.POST.get('collections_per_month', '1'))
            auctions_per_month = int(request.POST.get('auctions_per_month', '1'))

            auction_type = request.POST.get('auction_type', 'monthly')
            auction_interval_months = request.POST.get('auction_interval_months')

            if auction_type == "interval":
                auction_interval_months = int(auction_interval_months or 0)
                if auction_interval_months <= 0:
                    raise ValueError
            else:
                auction_interval_months = None

            date_input = request.POST.get('start_date')
            try:
                start_date = datetime.strptime(date_input, "%d-%m-%Y").date()
            except ValueError:
                start_date = datetime.strptime(date_input, "%Y-%m-%d").date()

            if not name or monthly_amount <= 0 or duration_months <= 0:
                raise ValueError
        except Exception:
            messages.error(request, "Invalid input data.")
            return redirect('chitti:add_group')

        total_amount = monthly_amount * duration_months

        # Main group
        main_group = ChittiGroup.objects.filter(owner=user, parent_group__isnull=True).first()

        # -----------------------------
        # CREATE GROUP FUNCTION
        # -----------------------------
        def create_group(parent=None):
            group = ChittiGroup.objects.create(
                owner=user,
                parent_group=parent,
                name=name,
                monthly_amount=monthly_amount,
                duration_months=duration_months,
                total_amount=total_amount,
                collections_per_month=collections_per_month,
                auctions_per_month=auctions_per_month,
                auction_type=auction_type,
                auction_interval_months=auction_interval_months,
                start_date=start_date
            )

            # 🔥 CREATE AUCTIONS (DB SAVE)
            base_dates = []
            for i in range(1, auctions_per_month + 1):
                d = request.POST.get(f"auction_date_{i}")
                if d:
                    base_dates.append(datetime.strptime(d, "%Y-%m-%d").date())

            group.create_auctions(base_dates=base_dates)
            return group

        # -----------------------------
        # MAIN GROUP CREATION
        # -----------------------------
        if not main_group:
            group = create_group()
            messages.success(request, "Main group created successfully ✅")
            return redirect('chitti:group_management')

        # -----------------------------
        # SUB GROUP CREATION
        # -----------------------------
        subscription = get_effective_subscription(main_group)
        if not subscription:
            messages.error(request, "Your subscription is expired or inactive.")
            return redirect('chitti:group_management')

        if not can_create_group(user):
            messages.error(request, f"You reached limit for {subscription.plan.name}")
            return redirect('chitti:group_management')

        group = create_group(parent=main_group)
        messages.success(request, f"Sub-group '{name}' created successfully ✅")
        return redirect('chitti:group_management')

    # GET request
    main_group = ChittiGroup.objects.filter(owner=user, parent_group__isnull=True).first()
    subscription = get_effective_subscription(main_group) if main_group else None
    remaining_groups = max(subscription.plan.max_groups - ChittiGroup.objects.filter(owner=user).count(), 0) if subscription else 0

    return render(request, "chitti/add_group.html", {
        "subscription": subscription,
        "plan": subscription.plan if subscription else None,
        "remaining_groups": remaining_groups,
    })

@login_required
def view_group(request, group_id):
    group = get_object_or_404(
        ChittiGroup,
        id=group_id,
        owner=request.user
    )

    # ================= MEMBERS =================
    members = group.chitti_members.all()
    total_members = members.count()

    # ================= AUCTIONS (ORDER FIXED) =================
    auctions = group.auctions.all().order_by('month_no', 'auction_no')

    # ================= PAYMENTS =================
    # Only admin received payments affect total_collected
    payments = Payment.objects.filter(
        group=group,
        payment_status='success'
    )

    total_collected = payments.filter(
        received_by_admin=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    pending_total = payments.filter(
        received_by_admin=False
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= MONTHLY POT =================
    monthly_pot = group.monthly_amount * total_members

    # ================= COMPLETED MONTHS =================
    completed_months = auctions.filter(
        winner__isnull=False
    ).values('month_no').distinct().count()

    # ================= CURRENT & REMAINING MONTHS =================
    current_month = completed_months + 1
    remaining_months = (group.duration_months or 0) - completed_months

    # ================= ADD PRIZE TO EACH AUCTION =================
    for auction in auctions:
        discount = auction.bid_amount or 0
        auction.prize = monthly_pot - discount

    # ================= LAST COMPLETED AUCTION =================
    last_auction = auctions.filter(
        winner__isnull=False
    ).order_by('month_no', 'auction_no').last()

    last_winner = None
    last_prize = None
    last_discount = None
    if last_auction:
        last_winner = last_auction.winner
        last_discount = last_auction.bid_amount or 0
        last_prize = monthly_pot - last_discount

    # ================= END DATE & EXPIRED CHECK =================
    end_date = None
    is_expired = False
    if group.start_date and group.duration_months:
        end_date = group.start_date + relativedelta(months=group.duration_months)
        if date.today() > end_date:
            is_expired = True

    # ================= CONTEXT =================
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
    auction = get_object_or_404(
        Auction,
        id=auction_id,
        group__owner=request.user
    )

    # 🔹 Already completed check
    if auction.is_closed:
        messages.warning(request, "Auction already completed")
        return redirect('chitti:auction_detail', auction_id=auction.id)

    # 🔥 DATE VALIDATION (IMPORTANT)
    today = timezone.now().date()

    if auction.auction_date > today:
        messages.error(
            request,
            f"Auction not started yet. Spin allowed on {auction.auction_date}"
        )
        return redirect('chitti:auction_detail', auction_id=auction.id)

    if auction.auction_date < today:
        messages.error(
            request,
            "Auction date already passed. You cannot spin now."
        )
        return redirect('chitti:auction_detail', auction_id=auction.id)

    # 🔹 All members
    all_members = ChittiMember.objects.filter(group=auction.group)

    # 🔹 Already won members
    previous_winners = auction.group.auctions.exclude(
        winner__isnull=True
    ).values_list('winner_id', flat=True)

    # 🔹 Eligible members only
    eligible_members = all_members.exclude(id__in=previous_winners)

    # 🔹 No members flag
    no_members = not eligible_members.exists()

    return render(
        request,
        'chitti/auction_spin.html',
        {
            'auction': auction,
            'members': eligible_members,
            'no_members': no_members  
        }
    )





@login_required
@require_POST
def assign_winner_ajax(request, auction_id):
    auction = get_object_or_404(
        Auction,
        id=auction_id,
        group__owner=request.user      
    )

    if auction.is_closed:
        return JsonResponse(
            {'success': False, 'error': 'Auction already closed'},
            status=400
        )

    all_members = ChittiMember.objects.filter(
        group=auction.group
    )

    previous_winners = auction.group.auctions.exclude(
        winner__isnull=True
    ).values_list('winner_id', flat=True)

    eligible_members = all_members.exclude(
        id__in=previous_winners
    )

    if not eligible_members.exists():
        return JsonResponse(
            {'success': False, 'error': 'No eligible members left'},
            status=400
        )

    # 🎯 Pick random winner
    winner = random.choice(list(eligible_members))

    # ✅ Assign winner safely
    auction.assign_winner(winner, bid_amount=0)

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

    return render(
        request,
        'chitti/auction_detail.html',
        {'auction': auction}
    )

# -----------------------------
 
@login_required
def admin_pending_payments(request):
    """
    Show ONLY REQUESTED CASH COLLECTOR payments
    """

    staff = request.user.staffprofile

    # 🔹 Get allowed groups
    if staff.role == 'admin':
        groups = ChittiGroup.objects.all()

    elif staff.role == 'group_admin':
        main_groups = ChittiGroup.objects.filter(owner=staff.user)
        sub_groups = ChittiGroup.objects.filter(parent_group__in=main_groups)
        groups = (main_groups | sub_groups).distinct()

    else:
        messages.error(request, "You are not authorized to view this page.")
        return redirect('home')

    # 🔥 FINAL FIX (VERY IMPORTANT)
    payments = Payment.objects.filter(
        payment_status='success',
        group__in=groups,
        collected_by__isnull=False,
        collected_by__role='collector',
        sent_to_admin=True   # ✅ ONLY REQUESTED PAYMENTS
    ).select_related(
        'member', 'group', 'collected_by'
    ).order_by('-paid_date', '-id')

    # 🔹 Group payments
    payments_by_group = defaultdict(list)

    for payment in payments:
        payments_by_group[payment.group].append(payment)

    # 🔹 Prepare data
    group_list = []

    for group, group_payments in payments_by_group.items():
        pending = [p for p in group_payments if not p.received_by_admin]
        approved = [p for p in group_payments if p.received_by_admin]

        group_list.append({
            'group': group,
            'payments': group_payments,
            'pending_payments': pending,
            'approved_payments': approved,
            'total_pending': sum(p.amount for p in pending),
            'total_approved': sum(p.amount for p in approved),
            'count_pending': len(pending),
            'count_approved': len(approved),
        })

    return render(request, 'chitti/admin_pending_payments.html', {
        'group_list': group_list
    })


@login_required
def group_payment_details(request, group_id):
    staff = request.user.staffprofile

    # 🔐 Permission check
    if staff.role == 'admin':
        group = get_object_or_404(ChittiGroup, id=group_id)

    elif staff.role == 'group_admin':
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=staff.user
        )
    else:
        messages.error(request, "Not allowed")
        return redirect('home')

    # 🔥 ONLY COLLECTOR PAYMENTS
    payments = Payment.objects.filter(
        group=group,
        payment_status='success',
        collected_by__isnull=False,
        collected_by__role='collector'
    ).select_related(
        'member',
        'collected_by__user'
    ).order_by('-paid_date')

    context = {
        'group': group,
        'payments': payments
    }

    return render(request, 'chitti/group_payment_details.html', context)
# -----------------------------
@login_required
def admin_approve_payment(request, payment_id):
    """
    Approve a single payment individually.
    """
    payment = get_object_or_404(Payment, id=payment_id)

    if payment.received_by_admin:
        messages.info(request, f"Payment of ₹{payment.amount} by {payment.member.name} is already approved.")
    else:
        payment.received_by_admin = True
        payment.save()
        messages.success(request, f"Payment of ₹{payment.amount} by {payment.member.name} approved successfully.")

    return redirect('chitti:admin_pending_payments')


# -----------------------------
@login_required
def admin_approve_payment_group(request, group_id):
    """
    Approve all payments for a specific group at once.
    """
    payments = Payment.objects.filter(
        group_id=group_id,
        payment_status='success',
        received_by_admin=False
    )

    total_amount = payments.aggregate(total=Sum('amount'))['total'] or 0

    if total_amount > 0:
        payments.update(received_by_admin=True)
        messages.success(request, f"All payments (₹{total_amount}) for this group approved successfully.")
    else:
        messages.info(request, "No pending payments to approve for this group.")

    return redirect('chitti:admin_pending_payments')