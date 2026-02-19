from datetime import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from accounts.decorators import group_admin_required, collector_required
from .models import Payment
from .forms import PaymentForm
from .models import Payment
from .forms import PaymentForm
from django.db import transaction
from django.core.paginator import Paginator
from django.utils import timezone  




# -----------------------------------
# GROUP ADMIN VIEWS
# -----------------------------------

@group_admin_required
def group_payment_list(request):
    main_group = request.user.staffprofile.group

    if not main_group:
        messages.error(request, "You are not assigned to any group.")
        return redirect('chitti:dashboard')

    groups = [main_group.id] + list(main_group.sub_groups.values_list('id', flat=True))

    # Initial Queryset
    payments_list = Payment.objects.filter(group_id__in=groups)\
        .select_related('member', 'collected_by', 'group')\
        .order_by('-paid_date')

    # Total collected (Calculated before pagination to include ALL records)
    total_collected = payments_list.filter(payment_status='success')\
        .aggregate(total=Sum('amount'))['total'] or 0

    # --- PAGINATION LOGIC ---
    # Show 10 payments per page
    paginator = Paginator(payments_list, 10) 
    page_number = request.GET.get('page')
    payments = paginator.get_page(page_number)
    # ------------------------

    return render(request, 'chitti/payment_list.html', {
        'payments': payments, # This is now a Page object
        'total_collected': total_collected
    })

@group_admin_required
@transaction.atomic
def group_payment_create(request):
    if request.method == 'POST':
        form = PaymentForm(request.POST, user=request.user)

        if form.is_valid():
            payment = form.save(commit=False)
            payment.collected_by = request.user.staffprofile

            # ✅ member group
            group = payment.member.assigned_chitti_group
            if not group:
                messages.error(request, "Selected member is not assigned to any group.")
                return redirect('payments:group_payment_create')

            # ✅ same month duplicate prevent
            paid_date = payment.paid_date or timezone.now().date()

            already_paid = Payment.objects.filter(
                member=payment.member,
                group=group,
                paid_date__year=paid_date.year,
                paid_date__month=paid_date.month,
                payment_status='success'
            ).exists()

            if already_paid:
                messages.error(
                    request,
                    f"{payment.member.name} already paid for this month!"
                )
                return redirect('payments:group_payment_create')

            # main group subscription
            main_group = group.parent_group if group.parent_group else group
            subscription = getattr(main_group, 'subscription', None)

            if not subscription or not subscription.is_active:
                messages.error(request, f"{main_group.name} has no active subscription!")
                return redirect('payments:group_payment_create')

            payment.subscription = subscription
            payment.subscription_start = subscription.start_date
            payment.subscription_end = subscription.end_date

            if not payment.paid_date:
                payment.paid_date = timezone.now().date()

            # force success
            payment.payment_status = "success"

            # save group also
            payment.group = group

            payment.save()

            messages.success(
                request,
                f"Payment for {payment.member.name} added successfully!"
            )
            return redirect('payments:group_payment_list')

    else:
        form = PaymentForm(user=request.user)

    return render(request, 'chitti/payment_form.html', {'form': form})



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
    payments = Payment.objects.filter(group=group).select_related('member','collected_by').order_by('-paid_date')
    total_collected = payments.filter(payment_status='success').aggregate(Sum('amount'))['amount__sum'] or 0
    return render(request, 'chitti/cash_collected_history.html', {
        'payments': payments,
        'total_collected': total_collected
    })


