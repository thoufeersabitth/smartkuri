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


from django.utils import timezone

@group_admin_required
@transaction.atomic
def group_payment_create(request):
    user = request.user
    selected_group = request.GET.get("group")
    paid_date = timezone.now().date()

    if request.method == "POST":
        form = PaymentForm(request.POST, user=user)
        if form.is_valid():
            payment = form.save(commit=False)
            member = payment.member
            chitti_member = get_object_or_404(
                ChittiMember,
                member=member,
                group_id=selected_group
            )
            group = chitti_member.group

            # Amount per collection
            collection_amount = group.monthly_amount / group.collections_per_month

            # Payments done this month
            existing_numbers = Payment.objects.filter(
                member=member,
                paid_date__year=paid_date.year,
                paid_date__month=paid_date.month,
                payment_status="success",
                group=group
            ).values_list('collection_number', flat=True)

            if len(existing_numbers) >= group.collections_per_month:
                messages.error(
                    request,
                    f"{member.name} already completed collections for {paid_date.strftime('%B %Y')}!"
                )
                return redirect("payments:group_payment_create")

            remaining_numbers = [i for i in range(1, group.collections_per_month+1) if i not in existing_numbers]
            payment.collection_number = remaining_numbers[0]
            payment.amount = collection_amount
            payment.group = group
            payment.collected_by = user.staffprofile
            payment.payment_status = "success"
            payment.received_by_admin = True
            payment.save()

            messages.success(
                request,
                f"₹{collection_amount} payment added for {member.name} (Collection #{payment.collection_number})"
            )
            return redirect("payments:group_payment_create")

    else:
        form = PaymentForm(user=user, initial_group=selected_group)

    # --- Prepare members for dropdown with extra info ---
    members = ChittiMember.objects.filter(group_id=selected_group) if selected_group else []
    member_collections_options = {}
    member_data = []

    for ch_member in members:
        existing_numbers = Payment.objects.filter(
            member=ch_member.member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month,
            payment_status="success",
            group=ch_member.group
        ).values_list('collection_number', flat=True)

        max_collections = ch_member.group.collections_per_month
        remaining_numbers = [i for i in range(1, max_collections+1) if i not in existing_numbers]
        member_collections_options[ch_member.member.id] = remaining_numbers

        # Send monthly_amount and collections to template for JS
        member_data.append({
            "id": ch_member.id,
            "member_id": ch_member.member.id,
            "name": ch_member.member.name,
            "monthly_amount": ch_member.group.monthly_amount,
            "collections": ch_member.group.collections_per_month
        })

    return render(
        request,
        "chitti/payment_form.html",
        {
            "form": form,
            "selected_group": selected_group,
            "members": member_data,
            "member_collections_options": member_collections_options,
        }
    )

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


