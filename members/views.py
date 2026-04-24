from datetime import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.contrib.auth.models import User
from dateutil.relativedelta import relativedelta
import random, string
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q
from collections import defaultdict
from accounts.decorators import member_required, group_admin_required
from accounts.models import StaffProfile
from members.models import Member
from payments.models import Payment
from chitti.models import Auction, ChittiGroup, ChittiMember
from subscriptions.utils import can_add_member, get_effective_subscription, get_subscription_status, get_time_left
from .forms import MemberAddForm, MemberEditForm
from django.db import models

# -----------------------------
# Helper: Generate random password
# -----------------------------
def generate_random_password(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# -----------------------------
# MEMBER DASHBOARD (FINAL)
# -----------------------------




@login_required
def member_dashboard(request):
    try:
        member = Member.objects.get(user=request.user)
    except Member.DoesNotExist:
        return render(request, 'member/error.html', {
            'message': 'Member profile not found.'
        })

    payments = Payment.objects.filter(member=member)
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

    group = member.assigned_chitti_group

    # ✅ safety check
    if not group:
        return render(request, 'member/error.html', {
            'message': 'No group assigned.'
        })

    total_amount = getattr(group, 'total_amount', 0)
    remaining = total_amount - total_paid

    today = timezone.now().date()

    # ✅ All completed auctions
    auctions = (
        Auction.objects
        .filter(group=group, winner__isnull=False)
        .select_related('winner__member__user')
        .order_by('auction_date')
    )

    # 🔥 ✅ CURRENT MONTH WINNER (IMPORTANT FIX)
    latest_auction = (
        Auction.objects
        .filter(
            group=group,
            auction_date__year=today.year,
            auction_date__month=today.month
        )
        .select_related('winner__member__user')
        .first()
    )

    # ✅ Logged-in member winner check
    is_winner = auctions.filter(winner__member=member).exists()

    context = {
        'member': member,
        'total_paid': total_paid,
        'total_amount': total_amount,
        'remaining': remaining,

        'auctions': auctions,
        'latest_auction': latest_auction,  # ✅ current month winner
        'is_winner': is_winner,
    }

    return render(request, 'member/member_dashboard.html', context)
# -----------------------------
# MEMBER PROFILE
# -----------------------------
@member_required
def member_profile(request):
    try:
        member_profile = Member.objects.get(user=request.user)
    except Member.DoesNotExist:
        return render(request, 'member/error.html', {'message': 'Member profile not found.'})

    return render(request, 'member/member_profile.html', {'member': member_profile})



@login_required
def member_payment_history(request):
    # 1. Get the logged-in member profile
    member = get_object_or_404(Member, user=request.user)

    # 2. Get the ChittiMember record with group details
    member_record = ChittiMember.objects.filter(member=member).select_related('group').first()
    
    if not member_record:
        return render(request, "member/no_subscriptions.html")

    group = member_record.group
    
    # 3. Fetch successful payments, optimized with select_related
    all_payments_qs = Payment.objects.filter(
        member=member,
        group=group,
        payment_status="success"
    ).select_related('collected_by__user').order_by("paid_date", "created_at")

    # 4. Calculation Logic
    monthly_amount = float(group.monthly_amount)
    duration = int(group.duration_months)
    current_grp_month = int(group.current_month)
    
    total_paid = float(all_payments_qs.aggregate(total=Sum("amount"))["total"] or 0)
    
    payment_rows = []
    payments_list = list(all_payments_qs)
    overflow_cash = 0.0
    active_payment = None

    for month in range(1, duration + 1):
        target = monthly_amount
        allocated_for_month = 0.0
        month_transactions = []

        while target > 0:
            # If no overflow remains, get the next payment from the list
            if overflow_cash <= 0:
                if payments_list:
                    active_payment = payments_list.pop(0)
                    overflow_cash = float(active_payment.amount)
                else:
                    break # No more payments available

            # Calculate the portion of payment to apply to this month
            take = min(overflow_cash, target)
            allocated_for_month += take
            
            # Logic to get collector name (Full Name fallback to Username)
            collector_display = "Admin"
            if active_payment.collected_by:
                user_obj = active_payment.collected_by.user
                collector_display = user_obj.get_full_name() or user_obj.username

            # Record this specific transaction slice
            month_transactions.append({
                "amount": take,
                "date": active_payment.paid_date,
                "collector": collector_display
            })

            overflow_cash -= take
            target -= take

        # Determine Payment Status for the month
        if allocated_for_month >= monthly_amount:
            status = "Paid"
        elif allocated_for_month > 0:
            status = "Partial"
        else:
            status = "Pending"

        payment_rows.append({
            "month": month,
            "target": monthly_amount,
            "paid": allocated_for_month,
            "balance": monthly_amount - allocated_for_month,
            "status": status,
            "transactions": month_transactions,
            "is_advance": month > current_grp_month and allocated_for_month > 0
        })

    # 5. Financial Summary
    total_due = max(0.0, (current_grp_month * monthly_amount) - total_paid)
    collections_paid = sum(1 for p in payment_rows if p["status"] == "Paid")

    context = {
        "group": group,
        "payment_rows": payment_rows,
        "total_paid": total_paid,
        "total_due": total_due,
        "collections_paid": collections_paid,
        "member_record": member_record,
    }

    return render(request, "member/member_payment_list.html", context)
@login_required
def member_auction_list(request):
    try:
        # Get the profile of the logged-in user
        member = Member.objects.select_related('assigned_chitti_group').get(user=request.user)
    except Member.DoesNotExist:
        return render(request, "member/error.html", {"message": "Member profile not found"})

    if not member.assigned_chitti_group:
        return render(request, "member/error.html", {"message": "You are not assigned to any group"})

    # Fetching auctions - Joins Winner -> Member -> User
    auctions = (
        Auction.objects
        .filter(group=member.assigned_chitti_group)
        .select_related('group', 'winner__member__user') 
        .order_by('auction_date')
    )

    return render(
        request,
        "member/member_auction_list.html",
        {
            "member": member,
            "group": member.assigned_chitti_group,
            "auctions": auctions,
            "today": timezone.now().date()
        }
    )


# GROUP ADMIN PROFILE
# -----------------------------
# -----------------------------
@group_admin_required
def group_admin_profile(request):
    profile = get_object_or_404(
        StaffProfile,
        user=request.user,
        role='group_admin'
    )

    # Groups under this admin
    groups = ChittiGroup.objects.filter(
        owner=request.user
    ).annotate(
        members_count=Count('chitti_members')
    )

    groups_count = groups.count()
    total_members_count = sum(g.members_count for g in groups)

    # Main group (for subscription)
    main_group = groups.filter(parent_group__isnull=True).first()

    effective_sub = get_effective_subscription(main_group) if main_group else None
    subscription_status = get_subscription_status(effective_sub) if effective_sub else None
    time_left = get_time_left(effective_sub) if effective_sub else "0"

    # 🔹 Max / Remaining groups
    max_groups = effective_sub.plan.max_groups if effective_sub else None
    remaining_groups = max_groups - groups_count if max_groups is not None else None

    # 🔹 Max / Remaining members
    max_members = effective_sub.plan.max_members if effective_sub else None
    remaining_members = max_members - total_members_count if max_members is not None else None

    context = {
        'profile': profile,
        'groups_count': groups_count,
        'members_count': total_members_count,
        'effective_sub': effective_sub,
        'subscription_status': subscription_status,
        'time_left': time_left,
        'max_groups': max_groups,
        'remaining_groups': remaining_groups,
        'max_members': max_members,
        'remaining_members': remaining_members,
    }

    return render(request, 'chitti/group_admin_profile.html', context)


# -----------------------------
# MEMBER LIST (Group Admin)
# -----------------------------
# -----------------------------
# MEMBER LIST (Group Admin)
@group_admin_required
def member_list(request):
    admin_user = request.user
    groups = ChittiGroup.objects.filter(owner=admin_user)

    # CHANGE: Query ChittiMember instead of Member
    # This makes 'm.id' in your loop refer to the ID that details/64/ needs
    members_qs = ChittiMember.objects.filter(
        group__in=groups
    ).select_related('member', 'group').order_by('id')

    q = request.GET.get('q', '').strip()
    if q:
        members_qs = members_qs.filter(
            Q(member__name__icontains=q) |
            Q(member__phone__icontains=q)
        )

    paginator = Paginator(members_qs, 10)
    page_number = request.GET.get('page')
    members = paginator.get_page(page_number)

    return render(request, 'chitti/group_member_list.html', {
        'members': members,
        'q': q,
    })
# -----------------------------
# MEMBER CREATE
# -----------------------------


@group_admin_required
def member_create(request):
    if request.method == 'POST':
        form = MemberAddForm(request.POST, admin_user=request.user)
        
        if form.is_valid():
            # Extract data from cleaned_data
            email = form.cleaned_data.get('email')
            phone = form.cleaned_data.get('phone')
            assigned_group = form.cleaned_data.get('assigned_chitti_group')
            password = form.cleaned_data.get('password')

            # 1. CHECK: Does a member with this Email or Phone already exist IN THIS GROUP?
            if assigned_group:
                # We check the ChittiMember table for duplicates within the specific group
                duplicate_exists = ChittiMember.objects.filter(
                    group=assigned_group
                ).filter(
                    Q(member__email=email) | Q(member__phone=phone)
                ).exists()

                if duplicate_exists:
                    # Fixed AttributeError: Using {assigned_group} directly calls the model's __str__
                    messages.error(request, f"A member with this Email or Phone already exists in the group: {assigned_group}")
                    return render(request, 'chitti/add_member.html', {'form': form})

                # 2. CHECK: Group capacity/limit
                if not can_add_member(assigned_group):
                    messages.error(request, "Cannot add member: Group limit reached or subscription expired.")
                    return render(request, 'chitti/add_member.html', {'form': form})

            try:
                # Create the Auth User (Username will be phone or email)
                # Note: This will fail if the User already exists globally in the system
                username = phone or email
                user = User.objects.create_user(
                    username=username,
                    password=password,
                    email=email
                )

                # Save the Member object
                member = form.save(commit=False)
                member.user = user
                member.is_first_login = True
                member.save()

                # Assign to ChittiMember table with Token Logic
                if assigned_group:
                    existing_tokens = ChittiMember.objects.filter(
                        group=assigned_group
                    ).values_list('token_no', flat=True)

                    next_token = max(existing_tokens, default=0) + 1

                    ChittiMember.objects.create(
                        group=assigned_group,
                        member=member,
                        token_no=next_token
                    )

                messages.success(request, f"Member '{member.name}' added successfully!")
                # Reset form for a fresh entry on the same page
                form = MemberAddForm(admin_user=request.user)
                
            except Exception as e:
                # Catching global uniqueness errors (e.g., username already exists in Django User table)
                messages.error(request, f"An error occurred: {str(e)}")
        else:
            # Form-level errors (like global unique constraints on the Member model)
            messages.error(request, "Please correct the errors shown below.")
            
    else:
        form = MemberAddForm(admin_user=request.user)

    return render(request, 'chitti/add_member.html', {'form': form})


# -----------------------------
# MEMBER EDIT
# -----------------------------
# views.py
@group_admin_required
def member_edit(request, pk):
    admin_user = request.user
    member = get_object_or_404(Member, pk=pk, assigned_chitti_group__owner=admin_user)

    if request.method == 'POST':
        form = MemberEditForm(request.POST, instance=member)
        if form.is_valid():
            # Optional: check group change limit
            new_group = form.cleaned_data.get('assigned_chitti_group')
            if new_group and new_group != member.assigned_chitti_group:
                if not can_add_member(new_group):
                    messages.error(request, "Cannot assign member: new group limit reached or subscription expired")
                    return redirect('members:member_list')

            form.save()
            messages.success(request, "Member updated successfully!")
            return redirect('members:member_list')
    else:
        form = MemberEditForm(instance=member)

    return render(request, 'chitti/add_member.html', {'form': form})



# -----------------------------
# MEMBER DELETE
# -----------------------------
@group_admin_required
def member_delete(request, pk):
    admin_user = request.user
    member = get_object_or_404(Member, pk=pk, assigned_chitti_group__owner=admin_user)
    member.delete()
    messages.success(request, "Member deleted successfully!")
    return redirect('members:member_list')





@login_required
def member_details(request, pk):
    # 1. Fetch the ChittiMember record
    member_record = get_object_or_404(ChittiMember, id=pk, group__owner=request.user)
    
    group = member_record.group
    member_profile = member_record.member # The actual 'Member' object

    # Configuration
    monthly_amount = float(group.monthly_amount)
    duration = int(group.duration_months)
    current_grp_month = int(group.current_month)
    
    # FIX: Use 'member' and 'group' instead of 'chitti_member'
    # Based on your error, these are the correct keywords for your Payment model
    all_payments = Payment.objects.filter(
        member=member_profile, 
        group=group,
        payment_status='success'
    ).order_by('paid_date', 'created_at')
    
    # ... rest of your calculation logic ...
    total_paid = float(all_payments.aggregate(total=Sum('amount'))['total'] or 0)
    temp_balance = total_paid 
    payment_rows = []

    for month in range(1, duration + 1):
        target = monthly_amount
        allocated = 0
        
        if temp_balance >= target:
            allocated = target
            temp_balance -= target
            status = "Paid"
        elif temp_balance > 0:
            allocated = temp_balance
            temp_balance = 0
            status = "Partial"
        else:
            allocated = 0
            status = "Pending"

        payment_rows.append({
            'month': month,
            'target': target,
            'paid': allocated,
            'balance': target - allocated,
            'status': status,
            'is_advance': month > current_grp_month and allocated > 0
        })

    context = {
        'member': member_record,
        'payment_rows': payment_rows,
        'total_paid': total_paid,
        'total_due': max(0, (current_grp_month * monthly_amount) - total_paid),
        'recent_transactions': all_payments,
        'total_collections': duration,
        'collections_paid': sum(1 for p in payment_rows if p['status'] == 'Paid'),
    }
    return render(request, 'chitti/member_details.html', context)