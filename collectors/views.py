from datetime import datetime, date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, F
from django.contrib.auth import logout

from members.models import Member
from chitti.models import ChittiGroup, ChittiMember
from payments.models import Payment
from accounts.decorators import collector_required
from django.utils import timezone


# ---------------------------------
# 👥 Assigned Members
# ---------------------------------
@login_required
@collector_required
def assigned_members(request):
    staff = request.user.staffprofile
    members = Member.objects.filter(assigned_chitti_group__collector=staff)
    q = request.GET.get('q')
    if q:
        members = members.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    return render(request, 'collector/members.html', {'members': members})


# ---------------------------------
# ➕ Add Collection (Payment)
# ---------------------------------
@login_required
@collector_required
def add_collection(request):
    staff = request.user.staffprofile
    members = Member.objects.filter(assigned_chitti_group__collector=staff)

    if request.method == 'POST':
        member = get_object_or_404(
            Member,
            id=request.POST.get('member'),
            assigned_chitti_group__collector=staff
        )

        amount = request.POST.get('amount')
        paid_date_str = request.POST.get('paid_date')
        method = request.POST.get('payment_method')

        # ✅ convert string → date
        paid_date = datetime.strptime(paid_date_str, "%Y-%m-%d").date()

        if not amount or float(amount) <= 0:
            messages.error(request, "Invalid amount")
            return redirect('collector:add')

        # ✅ monthly duplicate check
        exists = Payment.objects.filter(
            member=member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month
        ).exists()

        if exists:
            messages.error(request, "This month payment already collected")
            return redirect('collector:add')

        Payment.objects.create(
            member=member,
            collected_by=staff,
            group=member.assigned_chitti_group,
            amount=amount,
            paid_date=paid_date,
            payment_method=method,
            payment_status='success'
        )

        messages.success(request, "Payment collected successfully")
        return redirect('collector:today')

    return render(request, 'collector/add.html', {'members': members})


# ---------------------------------
# 📄 Today Collections
# ---------------------------------
@login_required
@collector_required
def today_collections(request):
    staff = request.user.staffprofile
    payments = Payment.objects.filter(collected_by=staff, paid_date=date.today(), payment_status='success').order_by('-id')
    total = payments.aggregate(total=Sum('amount'))['total'] or 0
    return render(request, 'collector/today.html', {'payments': payments, 'total': total})

@login_required
@collector_required
def pending_members(request):
    staff = request.user.staffprofile
    today = timezone.now().date()

    status = request.GET.get('status', 'pending')  # pending / success

    chitti_members = ChittiMember.objects.filter(
        group__collector=staff,
        group__is_active=True
    ).select_related('member', 'group')

    member_list = []

    for cm in chitti_members:
        group = cm.group

        current_month = (
            (today.year - group.start_date.year) * 12
            + (today.month - group.start_date.month)
            + 1
        )

        if current_month < 1 or current_month > group.duration_months:
            continue

        paid_amount = Payment.objects.filter(
            member=cm.member,
            group=group,
            paid_date__year=today.year,
            paid_date__month=today.month,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # ================= LOGIC =================

        if status == "pending" and paid_amount < group.monthly_amount:
            member_list.append({
                'member': cm.member,
                'group': group.name,
                'month': today.strftime('%B %Y'),
                'paid': paid_amount,
                'due': group.monthly_amount - paid_amount,
                'status': 'Pending'
            })

        elif status == "success" and paid_amount >= group.monthly_amount:
            member_list.append({
                'member': cm.member,
                'group': group.name,
                'month': today.strftime('%B %Y'),
                'paid': paid_amount,
                'due': 0,
                'status': 'Success'
            })

    return render(
        request,
        'collector/pending.html',
        {
            'member_list': member_list,
            'current_status': status
        }
    )


# ---------------------------------
# 🧾 Payment Receipt
# ---------------------------------
@login_required
@collector_required
def receipt(request, payment_id):
    staff = request.user.staffprofile
    payment = get_object_or_404(Payment, id=payment_id, collected_by=staff)
    return render(request, 'collector/receipt.html', {'payment': payment})


# ---------------------------------
# ✏️ Edit Payment (Same Day Only)
# ---------------------------------

@login_required
@collector_required
def edit_payment(request, payment_id):
    staff = request.user.staffprofile
    payment = get_object_or_404(Payment, id=payment_id, collected_by=staff)

    # ✅ Get only members assigned to this collector
    members = Member.objects.filter(assigned_chitti_group__collector=staff)

    if request.method == 'POST':
        member = get_object_or_404(
            Member,
            id=request.POST.get('member'),
            assigned_chitti_group__collector=staff
        )

        amount = request.POST.get('amount')
        paid_date_str = request.POST.get('paid_date')
        method = request.POST.get('payment_method')

        # convert string to date
        paid_date = datetime.strptime(paid_date_str, "%Y-%m-%d").date()

        # monthly duplicate check (skip current payment)
        exists = Payment.objects.filter(
            member=member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month
        ).exclude(id=payment.id).exists()

        if exists:
            messages.error(request, "This month payment already exists")
            return redirect('collector:edit_payment', payment_id=payment.id)

        # update payment
        payment.member = member
        payment.amount = amount
        payment.paid_date = paid_date
        payment.payment_method = method
        payment.save()

        messages.success(request, "Payment updated successfully")
        return redirect('collector:today')

    context = {
        'payment': payment,
        'members': members
    }
    return render(request, 'collector/edit_payment.html', context)

# ---------------------------------
# 🗑️ Delete Payment (Same Day Only)
# ---------------------------------
@login_required
@collector_required
def delete_payment(request, payment_id):
    staff = request.user.staffprofile
    payment = get_object_or_404(Payment, id=payment_id, collected_by=staff, paid_date=date.today())
    payment.delete()
    messages.success(request, "Payment deleted")
    return redirect('collector:today')


# ---------------------------------
# 👤 Collector Profile
# ---------------------------------
@login_required
@collector_required
def profile(request):
    collector = request.user.staffprofile
    assigned_groups = ChittiGroup.objects.filter(collector=collector)
    return render(request, 'collector/profile.html', {
        'collector': collector,
        'assigned_groups': assigned_groups
    })

@login_required
@collector_required
def member_history(request, member_id):
    staff = request.user.staffprofile

    member = get_object_or_404(
        Member,
        id=member_id,
        assigned_chitti_group__collector=staff
    )

    payments = Payment.objects.filter(
        member=member,
        payment_status='success'
    ).order_by('-paid_date')

    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

    # 🔥 NEW ADDITIONS (Minimal Change)
    group = member.assigned_chitti_group

    total_months = group.duration_months
    monthly_amount = group.monthly_amount
    total_kuri_amount = group.total_amount

    pending_amount = max(total_kuri_amount - total_paid, 0)

    context = {
        'member': member,
        'payments': payments,
        'total_paid': total_paid,

        # 🔥 Added values
        'total_months': total_months,
        'monthly_amount': monthly_amount,
        'total_kuri_amount': total_kuri_amount,
        'pending_amount': pending_amount,
    }

    return render(request, 'collector/history.html', context)

@login_required
@collector_required
def reports(request):
    staff = request.user.staffprofile
    today = date.today()

    # Base queryset
    qs = Payment.objects.filter(
        collected_by=staff,
        payment_status='success'
    ).select_related("member", "group")

    # Daily and monthly totals (today / this month)
    daily_total = qs.filter(paid_date=today).aggregate(total=Sum('amount'))['total'] or 0
    monthly_total = qs.filter(
        paid_date__year=today.year,
        paid_date__month=today.month
    ).aggregate(total=Sum('amount'))['total'] or 0

    # ================= Paid Members List =================
    from_date = request.GET.get('from')
    to_date = request.GET.get('to')

    if from_date or to_date:
        # Custom date range filter if user selects From/To
        filtered_qs = qs
        if from_date:
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
            filtered_qs = filtered_qs.filter(paid_date__gte=from_date_obj)
        if to_date:
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
            filtered_qs = filtered_qs.filter(paid_date__lte=to_date_obj)
        paid_members = filtered_qs.order_by('-paid_date')
    else:
        # Default: only current month
        paid_members = qs.filter(
            paid_date__year=today.year,
            paid_date__month=today.month
        ).order_by('-paid_date')

    context = {
        'daily_total': daily_total,
        'monthly_total': monthly_total,
        'paid_members': paid_members,
        'today': today,
        'from_date': from_date or '',
        'to_date': to_date or '',
    }

    return render(request, "collector/reports.html", context)

# ---------------------------------
# 🚪 Logout
# ---------------------------------
@login_required
def logout_view(request):
    logout(request)
    return redirect('accounts:login')
