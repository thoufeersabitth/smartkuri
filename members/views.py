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

from accounts.decorators import member_required, group_admin_required
from accounts.models import StaffProfile
from members.models import Member
from payments.models import Payment
from chitti.models import Auction, ChittiGroup, ChittiMember
from subscriptions.utils import can_add_member, get_effective_subscription, get_subscription_status, get_time_left
from .forms import MemberAddForm, MemberEditForm

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
    total_amount = getattr(group, 'total_amount', 0)
    remaining = total_amount - total_paid

    # 🔥 Auction logic
    auctions = Auction.objects.filter(
        group=group,
        winner__isnull=False
    ).order_by('auction_date')

    # Latest (current month) auction
    latest_auction = auctions.last()

    # Logged-in member ever won?
    is_winner = auctions.filter(winner__member=member).exists()

    context = {
        'member': member,
        'total_paid': total_paid,
        'total_amount': total_amount,
        'remaining': remaining,

        # winner related
        'auctions': auctions,            # all winners so far
        'latest_auction': latest_auction,
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
    # logged-in member
    member = get_object_or_404(Member, user=request.user)

    # queryset (ONLY this member)
    payments_list = (
        Payment.objects
        .filter(member=member)
        .select_related(
            "member__user",
            "group",
            "collected_by__user"
        )
        .order_by("-paid_date")
    )

    # total paid (success only)
    total_paid = payments_list.filter(
        payment_status="success"
    ).aggregate(
        total=Sum("amount")
    )["total"] or 0

    # pagination
    paginator = Paginator(payments_list, 10)
    page_number = request.GET.get("page")
    payments = paginator.get_page(page_number)

    return render(
        request,
        "member/member_payment_list.html",
        {
            "payments": payments,
            "total_paid": total_paid
        }
    )
@login_required
def member_auction_list(request):
    try:
        # 🔹 Logged-in user → Member profile
        member = Member.objects.select_related(
            'assigned_chitti_group'
        ).get(user=request.user)
    except Member.DoesNotExist:
        return render(request, "member/error.html", {
            "message": "Member profile not found"
        })

    # 🔒 SAFETY: member must be assigned to a group
    if not member.assigned_chitti_group:
        return render(request, "member/error.html", {
            "message": "You are not assigned to any chitti group"
        })

    # ✅ ONLY this member's group auctions
    auctions = (
        Auction.objects
        .select_related('group', 'winner', 'winner__member')
        .filter(group=member.assigned_chitti_group)
        .order_by('auction_date')
    )

    return render(
        request,
        "member/member_auction_list.html",
        {
            "member": member,
            "group": member.assigned_chitti_group,
            "auctions": auctions
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

    members_qs = Member.objects.filter(
        assigned_chitti_group__in=groups
    ).order_by('id')

    q = request.GET.get('q', '').strip()
    if q:
        members_qs = members_qs.filter(
            Q(name__icontains=q) |
            Q(phone=q)
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
            member = form.save(commit=False)

            if member.assigned_chitti_group:
                if not can_add_member(member.assigned_chitti_group):
                    messages.error(request, "Cannot add member: group limit reached or subscription expired")
                    return redirect('members:member_list')

            username = member.phone or member.email
            password = form.cleaned_data['password']

            user = User.objects.create_user(
                username=username,
                password=password,
                email=member.email
            )

            member.user = user
            member.is_first_login = True
            member.save()

            if member.assigned_chitti_group:
                existing_tokens = ChittiMember.objects.filter(
                    group=member.assigned_chitti_group
                ).values_list('token_no', flat=True)

                next_token = max(existing_tokens, default=0) + 1

                ChittiMember.objects.create(
                    group=member.assigned_chitti_group,
                    member=member,
                    token_no=next_token
                )

            # ✅ Secure message
            messages.success(request, "Member added successfully.")
            return redirect('members:member_list')
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
    member_record = get_object_or_404(
        ChittiMember,
        member__id=pk,
        group__owner=request.user
    )

    group = member_record.group
    duration_months = group.duration_months

    # All successful payments
    payments = list(
        Payment.objects.filter(
            member=member_record.member,
            group=group,
            payment_status='success'
        ).order_by('paid_date')
    )

    total_collected = sum(p.amount for p in payments)
    total_due = member_record.pending_amount

    month_wise = []
    payment_index = 0

    for month_no in range(1, duration_months + 1):

        if payment_index < len(payments):
            payment = payments[payment_index]

            month_wise.append({
                'month': month_no,
                'amount': payment.amount,  # ✅ EXACT COLLECTED AMOUNT
                'paid_date': payment.paid_date,
                'collector': (
                    payment.collected_by.user.get_full_name()
                    if payment.collected_by and payment.collected_by.user
                    else "Admin"
                ),
                'status': 'Paid',
            })

            payment_index += 1
        else:
            month_wise.append({
                'month': month_no,
                'amount': None,          # ✅ Pending month → blank
                'paid_date': None,
                'collector': None,
                'status': 'Pending',
            })

    context = {
        'member': member_record,
        'month_wise': month_wise,
        'total_collected': total_collected,
        'total_due': total_due,
        'months_paid': payment_index,
        'duration_months': duration_months,
    }

    return render(request, 'chitti/member_details.html', context)
