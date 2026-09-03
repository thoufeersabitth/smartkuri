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
# Helper: Get all Kuris for Member
# -----------------------------
def get_user_member_kuris(user):
    if not user or not user.is_authenticated:
        return []

    kuris_list = []
    members = Member.objects.filter(Q(user=user) | Q(email=user.email) | Q(phone=user.username))
    group_ids = set()
    for m in members:
        if m.assigned_chitti_group_id:
            group_ids.add(m.assigned_chitti_group_id)
        for cm in m.chitti_memberships.all():
            group_ids.add(cm.group_id)

    if group_ids:
        groups = ChittiGroup.objects.filter(id__in=group_ids)
        for g in groups:
            kuris_list.append(g)

    return kuris_list


# -----------------------------
# VIEW: Switch Active Kuri
# -----------------------------
@login_required
def switch_kuri(request, group_id):
    group = get_object_or_404(ChittiGroup, id=group_id)
    request.session['active_group_id'] = group.id
    messages.success(request, f"Switched active Kuri to '{group.name}'.")
    return redirect('members:member_dashboard')


# -----------------------------
# GET CURRENT MEMBER (ACTIVE KURI)
# -----------------------------
def get_current_member(request):
    if not request.user or not request.user.is_authenticated:
        return None

    user = request.user
    active_group_id = request.session.get('active_group_id')

    if active_group_id:
        m = Member.objects.filter(
            Q(user=user) | Q(email=user.email) | Q(phone=user.username),
            assigned_chitti_group_id=active_group_id
        ).first()
        if not m:
            cm = ChittiMember.objects.filter(
                Q(member__user=user) | Q(member__email=user.email) | Q(member__phone=user.username),
                group_id=active_group_id
            ).select_related('member').first()
            if cm:
                m = cm.member
        if m:
            return m

    m = Member.objects.filter(Q(user=user) | Q(email=user.email) | Q(phone=user.username)).first()
    if m and not active_group_id and m.assigned_chitti_group_id:
        request.session['active_group_id'] = m.assigned_chitti_group_id
    return m


# -----------------------------
# MEMBER DASHBOARD (FINAL)
# -----------------------------
@login_required
def member_dashboard(request):
    member = get_current_member(request)

    if not member:
        if hasattr(request.user, 'staffprofile'):
            role = request.user.staffprofile.role
            if role == 'admin':
                return redirect('adminpanel:dashboard')
            elif role == 'collector':
                return redirect('accounts:collector_dashboard')
            elif role == 'group_admin':
                return redirect('accounts:group_admin_dashboard')

        return render(request, 'member/error.html', {
            'message': 'Member profile not found for this account.'
        })

    # 🔒 FIRST LOGIN PASSWORD CHANGE CHECK
    if getattr(member, 'is_first_login', False):
        return redirect('accounts:change_password')

    active_group_id = request.session.get('active_group_id')
    group = None

    if active_group_id:
        group = ChittiGroup.objects.filter(id=active_group_id, is_active=True).first()

    if not group:
        group = member.assigned_chitti_group
        if not group:
            cm = ChittiMember.objects.filter(member=member).first()
            if cm:
                group = cm.group

    if not group:
        if hasattr(request.user, 'staffprofile'):
            return redirect('accounts:group_admin_dashboard')
        return render(request, 'member/error.html', {
            'message': 'No group assigned to this member account.'
        })

    payments = Payment.objects.filter(member=member, group=group)
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

    total_amount = getattr(group, 'total_amount', 0)
    remaining = max(0, total_amount - total_paid)

    today = timezone.now().date()

    # All completed auctions for this group
    auctions = (
        Auction.objects
        .filter(group=group, winner__isnull=False)
        .select_related('winner__member__user')
        .order_by('auction_date')
    )

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

    cm = ChittiMember.objects.filter(member=member, group=group).first()
    token_no = cm.token_no if cm else getattr(member, 'token_no', None)
    is_winner = auctions.filter(winner__member=member).exists()

    my_kuris = get_user_member_kuris(request.user)
    is_group_admin = hasattr(request.user, 'staffprofile') or StaffProfile.objects.filter(Q(user=request.user) | Q(user__email=request.user.email) | Q(phone=request.user.username)).exists()

    context = {
        'member': member,
        'group': group,
        'token_no': token_no,
        'total_paid': total_paid,
        'total_amount': total_amount,
        'remaining': remaining,
        'my_kuris': my_kuris,
        'is_group_admin': is_group_admin,

        'auctions': auctions,
        'latest_auction': latest_auction,
        'is_winner': is_winner,
    }

    return render(request, 'member/member_dashboard.html', context)


# -----------------------------
# MEMBER PROFILE
# -----------------------------
@login_required
def member_profile(request):
    member = get_current_member(request)

    if not member:
        if hasattr(request.user, 'staffprofile'):
            return redirect('accounts:group_admin_dashboard')
        return render(request, 'member/error.html', {'message': 'Member profile not found.'})

    if getattr(member, 'is_first_login', False):
        return redirect('accounts:change_password')

    return render(request, 'member/member_profile.html', {'member': member})


# -----------------------------
# MEMBER PAYMENT HISTORY
# -----------------------------
@login_required
def member_payment_history(request):
    member = get_current_member(request)

    if not member:
        if hasattr(request.user, 'staffprofile'):
            return redirect('accounts:group_admin_dashboard')
        return render(request, 'member/error.html', {'message': 'Member profile not found.'})

    if getattr(member, 'is_first_login', False):
        return redirect('accounts:change_password')

    active_group_id = request.session.get('active_group_id')
    group = None

    if active_group_id:
        group = ChittiGroup.objects.filter(id=active_group_id, is_active=True).first()

    if not group:
        group = member.assigned_chitti_group
        if not group:
            cm = ChittiMember.objects.filter(member=member).first()
            if cm:
                group = cm.group

    if not group:
        return render(request, "member/no_subscriptions.html")
    
    # Fetch successful payments
    all_payments_qs = Payment.objects.filter(
        member=member,
        group=group,
        payment_status="success"
    ).select_related('collected_by__user').order_by("paid_date", "created_at")

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
            if overflow_cash <= 0:
                if payments_list:
                    active_payment = payments_list.pop(0)
                    overflow_cash = float(active_payment.amount)
                else:
                    break

            take = min(overflow_cash, target)
            allocated_for_month += take
            
            collector_display = "Admin"
            if active_payment.collected_by:
                user_obj = active_payment.collected_by.user
                collector_display = user_obj.get_full_name() or user_obj.username

            month_transactions.append({
                "amount": take,
                "date": active_payment.paid_date,
                "collector": collector_display
            })

            overflow_cash -= take
            target -= take

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

    total_kuri_amount = float(group.total_amount or (duration * monthly_amount))
    total_due = max(0.0, total_kuri_amount - total_paid)
    collections_paid = sum(1 for p in payment_rows if p["status"] == "Paid")

    my_kuris = get_user_member_kuris(request.user)
    is_group_admin = hasattr(request.user, 'staffprofile') or StaffProfile.objects.filter(Q(user=request.user) | Q(user__email=request.user.email) | Q(phone=request.user.username)).exists()

    context = {
        "group": group,
        "payment_rows": payment_rows,
        "total_paid": total_paid,
        "total_due": total_due,
        "collections_paid": collections_paid,
        "member": member,
        "my_kuris": my_kuris,
        "is_group_admin": is_group_admin,
    }

    return render(request, "member/member_payment_list.html", context)


# -----------------------------
# MEMBER AUCTION LIST
# -----------------------------
@login_required
def member_auction_list(request):
    member = get_current_member(request)

    if not member:
        if hasattr(request.user, 'staffprofile'):
            return redirect('accounts:group_admin_dashboard')
        return render(request, "member/error.html", {"message": "Member profile not found"})

    if getattr(member, 'is_first_login', False):
        return redirect('accounts:change_password')

    active_group_id = request.session.get('active_group_id')
    group = None

    if active_group_id:
        group = ChittiGroup.objects.filter(id=active_group_id).first()

    if not group:
        group = member.assigned_chitti_group

    if not group:
        return render(request, "member/error.html", {"message": "You are not assigned to any group"})

    auctions = (
        Auction.objects
        .filter(group=group)
        .select_related('group', 'winner__member__user') 
        .order_by('auction_date')
    )

    return render(
        request,
        "member/member_auction_list.html",
        {
            "member": member,
            "group": group,
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
# AJAX SEARCH EXISTING USER
# -----------------------------
def search_existing_user(request):
    """
    AJAX Endpoint: Searches for existing SmartKuri users by Phone, Email, or Name.
    Returns list of matching users for live autocomplete dropdown.
    """
    from django.http import JsonResponse
    identifier = request.GET.get('identifier', '').strip()
    if not identifier or len(identifier) < 2:
        return JsonResponse({'exists': False, 'results': []})

    # Search Members matching query
    members_qs = Member.objects.filter(
        Q(email__icontains=identifier) | Q(phone__icontains=identifier) | Q(name__icontains=identifier)
    ).select_related('user')[:5]

    results = []
    seen_user_ids = set()

    for m in members_qs:
        uid = m.user_id if m.user else None
        if uid and uid in seen_user_ids:
            continue
        if uid:
            seen_user_ids.add(uid)
        
        results.append({
            'user_id': uid,
            'name': m.name,
            'email': m.email or '',
            'phone': m.phone or ''
        })

    if len(results) < 5:
        users_qs = User.objects.filter(
            Q(email__icontains=identifier) | Q(username__icontains=identifier) | Q(first_name__icontains=identifier)
        ).exclude(id__in=seen_user_ids)[:5]

        for u in users_qs:
            results.append({
                'user_id': u.id,
                'name': u.get_full_name() or u.username,
                'email': u.email or '',
                'phone': u.username
            })

    first_match = results[0] if results else None

    return JsonResponse({
        'exists': len(results) > 0,
        'results': results,
        'user_id': first_match['user_id'] if first_match else None,
        'name': first_match['name'] if first_match else '',
        'email': first_match['email'] if first_match else '',
        'phone': first_match['phone'] if first_match else ''
    })


# -----------------------------
# MEMBER CREATE
# -----------------------------
@group_admin_required
def member_create(request):
    if request.method == 'POST':
        form = MemberAddForm(request.POST, admin_user=request.user)
        
        if form.is_valid():
            email = form.cleaned_data.get('email')
            phone = form.cleaned_data.get('phone')
            assigned_group = form.cleaned_data.get('assigned_chitti_group')
            password = form.cleaned_data.get('password')
            existing_user_id = form.cleaned_data.get('existing_user_id')

            # 1. CHECK: Duplicate in this group
            if assigned_group:
                duplicate_exists = ChittiMember.objects.filter(
                    group=assigned_group
                ).filter(
                    Q(member__email=email) | Q(member__phone=phone)
                ).exists()

                if duplicate_exists:
                    messages.warning(request, f"Member '{email or phone}' is ALREADY enrolled in group '{assigned_group.name}'. Please select a different Chitti Group to enroll them.")
                    return render(request, 'chitti/add_member.html', {'form': form})

                if not can_add_member(assigned_group):
                    messages.error(request, "Cannot add member: Group limit reached or subscription expired.")
                    return render(request, 'chitti/add_member.html', {'form': form})

            try:
                user = None
                if existing_user_id:
                    user = User.objects.filter(id=existing_user_id).first()

                if not user:
                    user = User.objects.filter(
                        Q(email=email) | Q(username=phone) | Q(username=email)
                    ).first()

                if not user:
                    if not password:
                        messages.error(request, "Password is required for new member registration.")
                        return render(request, 'chitti/add_member.html', {'form': form})

                    username = phone or email
                    user = User.objects.create_user(
                        username=username,
                        password=password,
                        email=email
                    )

                member = Member.objects.filter(user=user).first()
                if not member:
                    member = form.save(commit=False)
                    member.user = user
                    member.is_first_login = True
                    member.save()
                else:
                    if form.cleaned_data.get('name'):
                        member.name = form.cleaned_data.get('name')
                    if form.cleaned_data.get('address'):
                        member.address = form.cleaned_data.get('address')
                    if form.cleaned_data.get('aadhaar_no'):
                        member.aadhaar_no = form.cleaned_data.get('aadhaar_no')
                    member.assigned_chitti_group = assigned_group
                    member.save()

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

                messages.success(request, f"Member '{member.name}' added successfully to group '{assigned_group.name}'!")
                form = MemberAddForm(admin_user=request.user)
                
            except Exception as e:
                messages.error(request, f"An error occurred: {str(e)}")
        else:
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