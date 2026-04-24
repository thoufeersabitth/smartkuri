from datetime import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from accounts.decorators import group_admin_required, collector_required
from chitti.models import ChittiGroup, ChittiMember
from members.models import Member
from .models import Payment
from .forms import PaymentForm
from .models import Payment
from .forms import PaymentForm
from django.db import transaction
from django.core.paginator import Paginator
from django.utils import timezone  
from django.contrib.auth.decorators import login_required



# -----------------------------------
# GROUP ADMIN VIEWS
# -----------------------------------


@login_required
@group_admin_required
def group_payment_list(request):
    # Fetch admin's main group
    main_group = request.user.staffprofile.group

    if not main_group:
        messages.error(request, "You are not assigned to any group.")
        return redirect('chitti:dashboard')

    # Include sub-groups for admin
    groups = [main_group.id] + list(main_group.sub_groups.values_list('id', flat=True))

    # Fetch payments for all groups
    payments_list = Payment.objects.filter(group_id__in=groups)\
        .select_related('member', 'collected_by', 'group')\
        .order_by('-paid_date')

    # Calculate totals
    total_collector_collected = payments_list.filter(payment_status='success').aggregate(total=Sum('amount'))['total'] or 0
    total_admin_collected = payments_list.filter(payment_status='success', received_by_admin=True).aggregate(total=Sum('amount'))['total'] or 0

    # Pagination
    paginator = Paginator(payments_list, 10)  # 10 payments per page
    page_number = request.GET.get('page')
    payments = paginator.get_page(page_number)

    return render(request, 'chitti/payment_list.html', {
        'payments': payments,  # Page object
        'total_collector_collected': total_collector_collected,
        'total_admin_collected': total_admin_collected,
    })
@group_admin_required
@transaction.atomic
def group_payment_create(request):
    user = request.user
    staff_profile = getattr(user, 'staffprofile', None) 
    
    selected_group_id = request.POST.get("group") or request.GET.get("group")
    admin_groups = ChittiGroup.objects.filter(owner=user)
    group = None
    member_data = []

    if selected_group_id and selected_group_id.isdigit():
        group = admin_groups.filter(id=selected_group_id).first()

    if request.method == "POST":
        form = PaymentForm(request.POST, user=user)

        if form.is_valid():
            try:
                if not group:
                    messages.error(request, "Group not found.")
                    return redirect(request.path)

                payment = form.save(commit=False)
                chitti_member_instance = form.cleaned_data.get('chitti_member')
                
                payment.member = chitti_member_instance.member
                payment.group = group
                
                if staff_profile:
                    payment.collected_by = staff_profile
                else:
                    messages.error(request, "Collector profile not found.")
                    return redirect(request.path)

                # 🔒 TOTAL LIMIT LOGIC
                total_months = int(group.duration_months)
                monthly_rate = float(group.monthly_amount)
                full_total_amount = total_months * monthly_rate

                actual_paid = float(Payment.objects.filter(
                    member=payment.member,
                    group=group,
                    payment_status='success'
                ).aggregate(Sum('amount'))['amount__sum'] or 0)

                new_amount = float(payment.amount)
                remaining = full_total_amount - actual_paid

                # ❌ Already completed
                if actual_paid >= full_total_amount:
                    messages.error(
                        request,
                        f"{payment.member.name} already completed full payment (₹{full_total_amount})."
                    )
                    return redirect(f"{request.path}?group={selected_group_id}")

                # 🔥 Auto adjust last payment
                if new_amount > remaining:
                    new_amount = remaining

                payment.amount = new_amount

                # ✅ SAVE + 🔔 NOTIFICATION FIX
                payment.payment_status = 'success'
                payment.sent_to_admin = True        # 🔥 IMPORTANT
                payment.admin_status = 'pending'    # 🔥 IMPORTANT
                payment.is_seen = False             # 🔥 IMPORTANT

                payment.save()

                messages.success(
                    request,
                    f"Payment of ₹{payment.amount} recorded for {payment.member.name}"
                )
                return redirect(f"{request.path}?group={selected_group_id}")

            except Exception as e:
                messages.error(request, f"Database Error: {str(e)}")
        else:
            messages.error(request, f"Form Error: {form.errors}")
    else:
        form = PaymentForm(user=user)

    # ===== STATUS LOGIC =====
    if group:
        current_month_no = int(group.current_month)
        monthly_rate = float(group.monthly_amount)
        total_expected_to_date = current_month_no * monthly_rate

        group_members = ChittiMember.objects.filter(group=group).select_related('member')

        for cm in group_members:
            actual_paid = float(Payment.objects.filter(
                member=cm.member, 
                group=group, 
                payment_status='success'
            ).aggregate(Sum('amount'))['amount__sum'] or 0)

            months_covered = int(actual_paid // monthly_rate)
            next_installment = months_covered + 1

            pending = max(0, total_expected_to_date - actual_paid)
            advance = max(0, actual_paid - total_expected_to_date)

            full_total_amount = float(group.total_amount)

            # 🔥 STATUS
            if actual_paid >= full_total_amount:
                status_label = "Completed ✅"
                is_advance_mode = False
            elif pending > 0:
                status_label = f"Due: ₹{pending:.2f}"
                is_advance_mode = False
            else:
                status_label = f"Advance: ₹{advance:.2f} (Month {next_installment} Next)"
                is_advance_mode = True

            member_data.append({
                "id": cm.id,
                "name": cm.member.name,
                "monthly_target": monthly_rate,
                "total_paid": actual_paid,
                "pending": pending,
                "advance": advance,
                "next_installment": next_installment,
                "status_label": status_label,
                "is_advance_mode": is_advance_mode,
                "is_completed": actual_paid >= full_total_amount,
            })

    return render(request, "chitti/payment_form.html", {
        "form": form,
        "admin_groups": admin_groups,
        "selected_group": selected_group_id,
        "members": member_data,
    })
# ==============================
# EDIT PAYMENT
# ==============================
@group_admin_required
def group_payment_edit(request, pk):

    payment = get_object_or_404(Payment, pk=pk)

    # ✅ permission check
    if payment.collected_by != request.user.staffprofile:
        messages.error(request, "You cannot edit this payment.")
        return redirect('payments:group_payment_list')

    if request.method == 'POST':
        form = PaymentForm(request.POST, instance=payment, user=request.user)

        if form.is_valid():
            form.save()
            messages.success(request, "Payment updated successfully!")
            return redirect('payments:group_payment_list')

    else:
        form = PaymentForm(instance=payment, user=request.user)

    return render(request, 'chitti/payment_form.html', {'form': form})

@group_admin_required
def group_payment_delete(request, pk):
    payment = get_object_or_404(
        Payment,
        pk=pk,
        collected_by=request.user.staffprofile
    )
    payment.delete()
    messages.success(request, "Payment deleted successfully!")
    return redirect('payments:group_payment_list')


@group_admin_required
def group_cash_collected_history(request):
    group = request.user.staffprofile.group

    # All payments for this group
    payments = Payment.objects.filter(
        group=group
    ).select_related('member','collected_by').order_by('-paid_date')

    # Total collected by admin (approved)
    total_admin_collected = payments.filter(
        payment_status='success',
        received_by_admin=True
    ).aggregate(total=Sum('amount'))['total'] or 0

    # Total collected by collector (all successful payments, regardless of admin approval)
    total_collector_collected = payments.filter(
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    return render(request, 'chitti/cash_collected_history.html', {
        'payments': payments,
        'total_admin_collected': total_admin_collected,
        'total_collector_collected': total_collector_collected,
    })


