from builtins import ValueError
from decimal import Decimal
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
# -----------------------------
@login_required
def group_management(request):
    groups = ChittiGroup.objects.filter(owner=request.user)

    if not groups.exists():
        return redirect('chitti:add_group')

    for group in groups:
        # calculate end date based on start date + duration months
        if group.start_date and group.duration_months:
            group.end_date_calculated = group.start_date + relativedelta(months=group.duration_months)
            group.duration_months = group.duration_months  # optional, just to show
        else:
            group.end_date_calculated = None  # Unlimited
            group.duration_months = None

        # check if expired
        if group.end_date_calculated and date.today() > group.end_date_calculated:
            group.is_expired = True
        else:
            group.is_expired = False

    return render(request, 'chitti/group_management.html', {'groups': groups})


@login_required
@transaction.atomic
def add_group(request):
    user = request.user

    # 🔒 Only group_admin allowed
    if not hasattr(user, 'staffprofile') or user.staffprofile.role != 'group_admin':
        messages.error(request, "Only group admins can create groups.")
        return redirect('chitti:group_management')

    # ---------------- POST ----------------
    if request.method == "POST":
        try:
            name = request.POST.get('name', '').strip()
            monthly_amount = Decimal(request.POST.get('monthly_amount', '0'))
            duration_months = int(request.POST.get('duration_months', '0'))
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

        # 🔍 Check main group
        main_group = ChittiGroup.objects.filter(
            owner=user,
            parent_group__isnull=True
        ).first()

        # ==================================================
        # CREATE MAIN GROUP (if not exists)
        # ==================================================
        if not main_group:
            ChittiGroup.objects.create(
                owner=user,
                name=name,
                monthly_amount=monthly_amount,
                duration_months=duration_months,
                total_amount=total_amount,
                start_date=start_date
            )

            messages.success(request, "Main group created successfully ✅")
            return redirect('chitti:group_management')

        # ==================================================
        # CREATE CHILD GROUP
        # ==================================================
        subscription = get_effective_subscription(main_group)

        if not subscription:
            messages.error(request, "Your subscription is expired or inactive.")
            return redirect('chitti:group_management')

        if not can_create_group(user):
            messages.error(
                request,
                f"You have reached the group limit for your {subscription.plan.name} plan."
            )
            return redirect('chitti:group_management')

        ChittiGroup.objects.create(
            owner=user,
            parent_group=main_group,
            name=name,
            monthly_amount=monthly_amount,
            duration_months=duration_months,
            total_amount=total_amount,
            start_date=start_date
        )

        messages.success(request, f"Sub-group '{name}' created successfully ✅")
        return redirect('chitti:group_management')

    # ---------------- GET ----------------
    main_group = ChittiGroup.objects.filter(
        owner=user,
        parent_group__isnull=True
    ).first()

    subscription = get_effective_subscription(main_group) if main_group else None

    remaining_groups = 0
    if subscription:
        total_groups = ChittiGroup.objects.filter(owner=user).count()
        remaining_groups = max(subscription.plan.max_groups - total_groups, 0)

    context = {
        "subscription": subscription,
        "plan": subscription.plan if subscription else None,
        "remaining_groups": remaining_groups,
    }

    return render(request, "chitti/add_group.html", context)




# -----------------------------
# View Group Details
# -----------------------------
@login_required
def view_group(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, owner=request.user)
    members = group.chitti_members.all()
    auctions = group.auctions.all()

    # 🔹 Calculate end date based on start date + duration months
    if group.start_date and getattr(group, 'duration_months', None):
        group.end_date_calculated = group.start_date + relativedelta(months=group.duration_months)
    else:
        group.end_date_calculated = None  # Unlimited

    # 🔹 Expired status
    if group.end_date_calculated and date.today() > group.end_date_calculated:
        group.is_expired = True
    else:
        group.is_expired = False

    return render(request, 'chitti/view_group.html', {
        'group': group,
        'members': members,
        'auctions': auctions,
    })

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
@login_required
def edit_group(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id, owner=request.user)

    if request.method == 'POST':
        group.name = request.POST.get('name')
        group.monthly_amount = Decimal(request.POST.get('monthly_amount'))
        group.duration_months = int(request.POST.get('duration_months'))
        group.start_date = request.POST.get('start_date')

        # Recalculate total_amount automatically
        group.total_amount = group.monthly_amount * group.duration_months
        group.save()
        messages.success(request, "Group updated successfully!")
        return redirect('chitti:group_management')

    return render(request, 'chitti/edit_group.html', {'group': group})


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


@login_required
def auction_list_group_view(request, group_id):
    group = get_object_or_404(
        ChittiGroup,
        id=group_id,
        owner=request.user
    )

    # Prepare months and auctions
    months = []
    auctions_sorted = group.auctions.all().order_by('auction_date')
    for i in range(1, group.duration_months + 1):
        auction = auctions_sorted[i-1] if i-1 < len(auctions_sorted) else None
        months.append({
            'month_no': i,
            'auction': auction
        })

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

        # 🔹 Convert date (from <input type="date">)
        try:
            auction_date = datetime.strptime(
                auction_date_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect("chitti:add_auction")

        # 🔹 Get group (only owner)
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 🔹 1️⃣ Check auction date inside duration
        group_end_date = group.start_date + relativedelta(
            months=group.duration_months
        )

        if auction_date < group.start_date or auction_date >= group_end_date:
            messages.error(request, "Auction date exceeds group duration period.")
            return redirect("chitti:add_auction")

        # 🔹 2️⃣ Same month duplicate check
        month_exists = group.auctions.filter(
            auction_date__year=auction_date.year,
            auction_date__month=auction_date.month
        ).exists()

        if month_exists:
            messages.error(request, "An auction already exists for this month.")
            return redirect("chitti:add_auction")

        # 🔹 3️⃣ Duration limit check
        total_auctions = group.auctions.count()

        if total_auctions >= group.duration_months:
            messages.error(request, "Auction limit reached for this group.")
            return redirect("chitti:add_auction")

        # ✅ Create Auction with automatic month_no
        Auction.objects.create(
            group=group,
            auction_date=auction_date,
            month_no=total_auctions + 1  # auto-increment month
        )

        messages.success(
            request,
            f"Auction created successfully (Auction #{total_auctions + 1})"
        )

        return redirect("chitti:auction_list")

    # GET request
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

    if auction.is_closed:
        messages.warning(request, "Auction already completed")
        return redirect('chitti:auction_detail', auction_id=auction.id)

    # All members in this group
    all_members = ChittiMember.objects.filter(group=auction.group)

    # Already won members
    previous_winners = auction.group.auctions.exclude(
        winner__isnull=True
    ).values_list('winner_id', flat=True)

    # Eligible members only
    eligible_members = all_members.exclude(id__in=previous_winners)

    # ✅ Pass a flag to template instead of redirecting
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
        group__owner=request.user      # 🔥 SECURITY
    )

    return render(
        request,
        'chitti/auction_detail.html',
        {'auction': auction}
    )
