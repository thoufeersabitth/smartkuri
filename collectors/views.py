from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Collection
from django.db import transaction

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q, F
from django.contrib.auth import logout
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

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
@transaction.atomic
def add_collection(request):
    staff = request.user.staffprofile
    today = timezone.now().date()

    # ---------------- SUMMARY ----------------
    all_payments = Payment.objects.filter(
        group__collector=staff,   # ✅ FIX
        payment_status='success'
    )

    total_amount = all_payments.aggregate(Sum('amount'))['amount__sum'] or 0
    admin_received = all_payments.filter(received_by_admin=True).aggregate(Sum('amount'))['amount__sum'] or 0
    sent_amount = all_payments.filter(sent_to_admin=True, received_by_admin=False).aggregate(Sum('amount'))['amount__sum'] or 0
    draft_amount = all_payments.filter(sent_to_admin=False).aggregate(Sum('amount'))['amount__sum'] or 0

    # ---------------- MEMBERS ----------------
    members = Member.objects.filter(
        assigned_chitti_group__collector=staff
    ).select_related('assigned_chitti_group')

    member_data = []

    for member in members:
        group = member.assigned_chitti_group
        if not group:
            continue

        monthly_rate = Decimal(group.monthly_amount)
        current_month_no = int(group.current_month or 0)

        total_expected_to_date = current_month_no * monthly_rate

        actual_paid = Payment.objects.filter(   # ✅ FIX (fresh query)
            member=member,
            group=group,
            payment_status='success'
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

        months_covered = int(actual_paid // monthly_rate) if monthly_rate else 0
        next_installment = months_covered + 1

        pending = max(Decimal('0'), total_expected_to_date - actual_paid)
        advance = max(Decimal('0'), actual_paid - total_expected_to_date)

        full_total_amount = Decimal(group.total_amount)

        if actual_paid >= full_total_amount:
            status_label = "Completed ✅"
            is_advance_mode = False
        elif pending > 0:
            status_label = f"Due: ₹{pending}"
            is_advance_mode = False
        else:
            status_label = f"Advance: ₹{advance} (Month {next_installment})"
            is_advance_mode = True

        member_data.append({
            "member_obj": member,
            "monthly_target": monthly_rate,
            "total_paid": actual_paid,
            "pending": pending,
            "advance": advance,
            "status_label": status_label,
            "is_advance_mode": is_advance_mode,
            "group_name": group.name,
            "is_completed": actual_paid >= full_total_amount
        })

    # ---------------- POST ----------------
    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        # ---------------- MEMBER COLLECTION ----------------
        if form_type == 'member_collection':
            try:
                member_id = request.POST.get('member')
                amount_input = Decimal(request.POST.get('amount') or 0)
                payment_method = request.POST.get('payment_method')
                paid_date = request.POST.get('paid_date')

                member = get_object_or_404(
                    Member,
                    id=member_id,
                    assigned_chitti_group__collector=staff
                )

                group = member.assigned_chitti_group

                full_total_amount = Decimal(group.monthly_amount) * group.duration_months

                actual_paid = Payment.objects.filter(   # ✅ FIX
                    member=member,
                    group=group,
                    payment_status='success'
                ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

                # duplicate check
                if Payment.objects.filter(
                    member=member,
                    group=group,
                    paid_date=paid_date or today,
                    payment_status='success'
                ).exists():
                    messages.error(request, "Already payment exists for this date")
                    return redirect('collector:add')

                # limit check
                if actual_paid + amount_input > full_total_amount:
                    remaining = full_total_amount - actual_paid
                    messages.error(request, f"Only ₹{remaining} allowed")
                    return redirect('collector:add')

                # SAVE
                Payment.objects.create(
                    member=member,
                    collected_by=staff,
                    group=group,
                    amount=amount_input,
                    paid_date=paid_date or today,
                    payment_method=payment_method.lower(),
                    payment_status='success',
                    sent_to_admin=False,
                    received_by_admin=False,   # correct flow
                    admin_status='pending'
                )

                messages.success(request, f"₹{amount_input} collected from {member.name}")
                return redirect('collector:add')

            except Exception as e:
                messages.error(request, str(e))

        # ---------------- SEND TO ADMIN ----------------
        elif form_type == 'send_to_admin':
            draft_payments = Payment.objects.filter(
                group__collector=staff,   # ✅ FIX
                sent_to_admin=False,
                payment_status='success'
            )

            total_sending = draft_payments.aggregate(Sum('amount'))['amount__sum'] or 0

            if total_sending > 0:
                draft_payments.update(sent_to_admin=True)
                messages.success(request, f"₹{total_sending} sent to admin")
            else:
                messages.warning(request, "No draft payments")

            return redirect('collector:add')

    return render(request, 'collector/add.html', {
        'members_data': member_data,
        'today': today,
        'total_amount': total_amount,
        'admin_received': admin_received,
        'sent_amount': sent_amount,
        'draft_amount': draft_amount,
    })



class HandoverPendingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        staff = request.user.staffprofile

        # ✅ total collected (all successful payments)
        total_collected = Payment.objects.filter(
            collected_by=staff,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # ✅ total sent to admin
        total_sent = Payment.objects.filter(
            collected_by=staff,
            payment_status='success',
            sent_to_admin=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        # ✅ pending (not yet sent)
        pending = Payment.objects.filter(
            collected_by=staff,
            payment_status='success',
            sent_to_admin=False,
            received_by_admin=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            "total_collected": total_collected,
            "total_sent": total_sent,
            "handover_pending": pending,
            "show_card": pending > 0
        })
    
# ---------------------------------
# -----------------------------
# -----------------------------
from datetime import date

from datetime import date
from collections import defaultdict
from collections import defaultdict
from datetime import date
from collections import defaultdict
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from datetime import date

@login_required
@collector_required
def all_collections(request):
    staff = request.user.staffprofile
    today = date.today()

    payments = Payment.objects.filter(
        collected_by=staff,
        payment_status='success'
    ).select_related('member', 'group').order_by('-paid_date')

    payments_by_group = defaultdict(list)

    for payment in payments:
        payment.is_today = (payment.paid_date == today)
        payments_by_group[payment.group].append(payment)

    group_list = []

    for group, group_payments in payments_by_group.items():

        total_collector = sum(p.amount for p in group_payments)

        total_admin = sum(
            p.amount for p in group_payments
            if p.received_by_admin
        )

        sent = sum(
            p.amount for p in group_payments
            if p.sent_to_admin
        )

        draft = sum(
            p.amount for p in group_payments
            if not p.sent_to_admin
        )

        # ✅ FIXED pending logic
        pending = sent - total_admin
        if pending < 0:
            pending = 0

        # 🔥 IMPORTANT: detect rejected payments (for resend button)
        has_rejected = any(
            p.admin_status == "rejected"
            for p in group_payments
        )

        group_list.append({
            'group': group,
            'payments': group_payments,
            'total_collector': total_collector,
            'total_admin': total_admin,
            'pending': pending,
            'not_sent': draft,
            'has_rejected': has_rejected,   # 🔥 ADD THIS
        })

    return render(request, 'collector/today.html', {
        'group_list': group_list
    })
@login_required
@collector_required
def request_admin_approval(request, group_id):
    """Send pending payments to admin for approval"""
    staff = request.user.staffprofile

    payments = Payment.objects.filter(
        collected_by=staff,
        group_id=group_id,
        payment_status='success',
        sent_to_admin=False,
        received_by_admin=False
    )

    total_amount = payments.aggregate(total=Sum('amount'))['total'] or 0

    if total_amount > 0:
        payments.update(sent_to_admin=True)
        messages.success(request, f"₹{total_amount} sent to admin for approval ✅")
    else:
        messages.info(request, "No pending payments to send.")

    return redirect('collector:all_collections')

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
@login_required
@collector_required
def delete_payment(request, payment_id):
    staff = request.user.staffprofile

    # ✅ ONLY ID + collector check
    payment = get_object_or_404(
        Payment,
        id=payment_id,
        collected_by=staff
    )

    # 🔥 CONDITION 1: Only today
    if payment.paid_date != date.today():
        messages.error(request, "Only today's payments can be deleted ❌")
        return redirect('collector:all_collections')

    # 🔥 CONDITION 2: Not sent to admin
    if payment.sent_to_admin:
        messages.error(request, "Cannot delete. Already sent to admin ❌")
        return redirect('collector:all_collections')

    payment.delete()
    messages.success(request, "Payment deleted successfully ✅")

    return redirect('collector:all_collections')

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
    current_date = timezone.now().date()

    # Fetch member and ensure they belong to the collector's assigned group
    member = get_object_or_404(
        Member,
        id=member_id,
        assigned_chitti_group__collector=staff
    )

    # Get successful payments only
    payments = Payment.objects.filter(
        member=member,
        payment_status='success'
    ).order_by('-paid_date')

    # Financial Calculations
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    group = member.assigned_chitti_group
    
    # Logic to handle the starting date of the Chitti
    start_date = group.start_date if hasattr(group, 'start_date') and group.start_date else current_date
    
    total_months = group.duration_months
    monthly_amount = float(group.monthly_amount)
    total_kuri_amount = float(group.total_amount) if hasattr(group, 'total_amount') and group.total_amount else (monthly_amount * total_months)
    
    temp_total_paid = float(total_paid)
    pending_amount = max(float(total_kuri_amount) - temp_total_paid, 0)

    month_status = []
    
    for i in range(1, total_months + 1):
        target = monthly_amount
        received = 0
        remaining = target
        
        # Calculate the approximate due date for this specific month
        month_due_date = start_date + timedelta(days=30 * (i - 1))
        is_future_month = month_due_date > current_date

        if temp_total_paid >= target:
            received = target
            remaining = 0
            # If paid for a month in the future, status is "Advance"
            status = "Advance" if is_future_month else "Full Paid"
            temp_total_paid -= target
        elif temp_total_paid > 0:
            received = temp_total_paid
            remaining = target - received
            status = "Partial"
            temp_total_paid = 0
        else:
            received = 0
            remaining = target
            status = "Pending"

        month_status.append({
            'month_num': i,
            'target': target,
            'received': received,
            'remaining': remaining,
            'status': status
        })

    context = {
        'member': member,
        'payments': payments,
        'total_paid': total_paid,
        'total_months': total_months,
        'monthly_amount': monthly_amount,
        'total_kuri_amount': total_kuri_amount,
        'pending_amount': pending_amount,
        'month_status': month_status,
    }

    return render(request, 'collector/history.html', context)
@login_required
@collector_required
def resend_payment(request, payment_id):
    staff = request.user.staffprofile

    payment = get_object_or_404(
        Payment,
        id=payment_id,
        collected_by=staff
    )

    # only rejected payments
    if payment.admin_status != 'rejected':
        messages.error(request, "Only rejected payments can be resent ❌")
        return redirect('collector:all_collections')

    # 🔥 reset + resend
    payment.admin_status = 'pending'
    payment.sent_to_admin = True
    payment.received_by_admin = False
    payment.save()

    messages.success(request, "Payment resubmitted to admin ✅")
    return redirect('collector:all_collections')


@login_required
@collector_required
def resend_group_payments(request, group_id):
    staff = request.user.staffprofile

    payments = Payment.objects.filter(
        collected_by=staff,
        group_id=group_id,
        admin_status='rejected'
    )

    if not payments.exists():
        messages.info(request, "No rejected payments to resend")
        return redirect('collector:all_collections')

    for p in payments:
        p.admin_status = 'pending'
        p.sent_to_admin = True
        p.received_by_admin = False
        p.save()

    messages.success(request, "All rejected payments resent to admin ✅")
    return redirect('collector:all_collections')


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
