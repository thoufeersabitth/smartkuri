from builtins import hasattr, sum
from email.headerregistry import Group
from itertools import count
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum
from django.contrib import messages
from django.db.models import Count, Sum  , Max# <- Count needed for annotations



from accounts import models
from accounts.models import StaffProfile
from chitti.models import ChittiGroup, ChittiMember
from members.models import Member
from subscriptions.models import GroupSubscription, SubscriptionPlan
from payments.models import Payment
from subscriptions.utils import get_subscription_status
from .models import SystemNotification
from .utils import admin_required

# ------------------------------ Dashboard ------------------------------
@admin_required
def dashboard(request):
    total_group_admins = StaffProfile.objects.filter(role='group_admin').count()
    blocked_admins = StaffProfile.objects.filter(role='group_admin', is_blocked=True).count()
    total_groups = ChittiGroup.objects.count()
    active_subscriptions = StaffProfile.objects.filter(role='group_admin', is_subscribed=True).count()
    expired_subscriptions = StaffProfile.objects.filter(role='group_admin', subscription_end__lt=timezone.now()).count()
    total_revenue = Payment.objects.aggregate(total=Sum('amount'))['total'] or 0

    recent_activities = StaffProfile.objects.filter(
        role='group_admin',
        subscription_end__gte=timezone.now()-timedelta(days=7)
    )

    return render(request, 'adminpanel/dashboard.html', {
        'total_group_admins': total_group_admins,
        'blocked_admins': blocked_admins,
        'total_groups': total_groups,
        'active_subscriptions': active_subscriptions,
        'expired_subscriptions': expired_subscriptions,
        'total_revenue': total_revenue,
        'recent_activities': recent_activities,
    })

# ------------------------------ Group Admins ------------------------------
# ------------------------------ Group Admins List ------------------------------
@admin_required
def group_admin_list(request):
    admins = StaffProfile.objects.filter(role='group_admin')
    admin_data = []

    for admin in admins:
        # Groups owned by this admin, annotated with member counts
        groups = ChittiGroup.objects.filter(owner=admin.user).annotate(
            members_count=Count('chitti_members')
        )
        groups_count = groups.count()
        total_members_count = sum(g.members_count for g in groups)

        # Last successful payment by this admin
        last_payment = Payment.objects.filter(collected_by=admin, payment_status='success').order_by('-paid_date').first()

        # Total paid amount
        total_paid = Payment.objects.filter(
            collected_by=admin,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Subscription info
        subscription_plan = last_payment.subscription_plan.name if last_payment and last_payment.subscription_plan else None
        subscription_start = last_payment.subscription_start if last_payment else None
        subscription_end = last_payment.subscription_end if last_payment else None
        is_subscription_active = subscription_end and subscription_end >= timezone.now().date() if last_payment else False

        admin_data.append({
            'profile': admin,
            'last_payment': last_payment,
            'last_payment_amount': last_payment.amount if last_payment else None,
            'last_payment_status': last_payment.payment_status if last_payment else None,
            'last_payment_method': last_payment.payment_method if last_payment else None,
            'last_payment_date': last_payment.paid_date if last_payment else None,
            'last_payment_time': last_payment.paid_time if last_payment else None,
            'last_payment_transaction_id': last_payment.transaction_id if last_payment else None,
            'last_payment_invoice': last_payment.invoice_number if last_payment else None,
            'last_payment_plan': subscription_plan,
            'total_paid': total_paid,
            'groups_count': groups_count,
            'members_count': total_members_count,
            'subscription_plan': subscription_plan,
            'subscription_start': subscription_start,
            'subscription_end': subscription_end,
            'is_subscription_active': is_subscription_active,
        })

    return render(request, 'adminpanel/group_admin_list.html', {'admins': admin_data})


@admin_required
def group_admin_detail(request, admin_id):
    admin = get_object_or_404(StaffProfile, id=admin_id)

    # ---------------- Payments ----------------
    payments = Payment.objects.filter(collected_by=admin).order_by('-paid_date')
    success_payments = payments.filter(payment_status='success')
    last_payment = success_payments.first()
    total_paid = success_payments.aggregate(total=Sum('amount'))['total'] or 0
    payment_count = payments.count()

    # ---------------- Subscription ----------------
    subscription = GroupSubscription.objects.filter(
        group__owner=admin.user
    ).order_by('-end_date').first()
    status = get_subscription_status(subscription)

    if subscription and subscription.is_active != status['active']:
        subscription.is_active = status['active']
        subscription.save(update_fields=['is_active'])

    # ---------------- Groups ----------------
    groups = ChittiGroup.objects.filter(owner=admin.user).annotate(member_count=Count('chitti_members'))
    groups_count = groups.count()
    members_count = sum(g.member_count for g in groups)

    # ---------------- Context ----------------
    context = {
        'admin': admin,
        'plan': subscription.plan if subscription else None,
        'subscription_active': status['active'],
        'subscription_start': subscription.start_date if subscription else None,
        'subscription_end': subscription.end_date if subscription else None,
        'days_left': status['days_left'],
        'hours_left': status.get('hours_left', 0),
        'groups': groups,
        'groups_count': groups_count,
        'members_count': members_count,
        'payments': payments,
        'last_payment': last_payment,
        'total_paid': total_paid,
        'payment_count': payment_count,
    }

    return render(request, 'adminpanel/group_admin_detail.html', context)

@admin_required
def block_group_admin(request, admin_id):
    profile = get_object_or_404(StaffProfile, id=admin_id)
    profile.is_blocked = True
    profile.save()
    messages.success(request, "Admin blocked successfully")
    return redirect('adminpanel:group_admin_list')

@admin_required
def unblock_group_admin(request, admin_id):
    profile = get_object_or_404(StaffProfile, id=admin_id)
    profile.is_blocked = False
    profile.save()
    messages.success(request, "Admin unblocked successfully")
    return redirect('adminpanel:group_admin_list')

@admin_required
def subscription_reports(request):
    today = timezone.now().date()
    admins = StaffProfile.objects.filter(role='group_admin')

    report_data = []

    for admin in admins:
        # Last successful payment
        last_payment = Payment.objects.filter(
            collected_by=admin,
            payment_status='success'
        ).order_by('-paid_date').first()

        plan = None
        start_date = None
        end_date = None
        days_left = None
        status = "No Subscription"
        show_renew = False

        if last_payment and last_payment.subscription_end:
            plan = last_payment.subscription_plan.name
            start_date = last_payment.subscription_start
            end_date = last_payment.subscription_end
            days_left = (end_date - today).days

            if days_left < 0:
                status = "Expired"
                show_renew = True
            elif days_left <= 7:
                status = "Expiring Soon"
                show_renew = True
            else:
                status = "Active"

        report_data.append({
            'admin': admin,
            'plan': plan,
            'start_date': start_date,
            'end_date': end_date,
            'days_left': days_left,
            'status': status,
            'show_renew': show_renew,
        })

    return render(
        request,
        'adminpanel/subscription_reports.html',
        {'reports': report_data}
    )


@admin_required
def renew_subscription(request, admin_id):
    admin = get_object_or_404(StaffProfile, id=admin_id, role='group_admin')
    plans = SubscriptionPlan.objects.all()

    if request.method == 'POST':
        plan_id = request.POST.get('plan')
        plan = get_object_or_404(SubscriptionPlan, id=plan_id)

        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=plan.duration_days)

        # Save subscription via payment-like logic
        Payment.objects.create(
            collected_by=admin,
            amount=plan.price,
            payment_status='success',
            payment_method='admin_renew',
            subscription_plan=plan,
            subscription_start=start_date,
            subscription_end=end_date,
        )

        messages.success(request, f"{admin.user.username} subscription renewed successfully")
        return redirect('adminpanel:subscription_reports')

    return render(
        request,
        'adminpanel/renew_subscription.html',
        {'admin': admin, 'plans': plans}
    )

# ------------------------------ Reports ------------------------------
@admin_required
def reports(request):
    groups = ChittiGroup.objects.all()
    admins = StaffProfile.objects.filter(role='group_admin')
    members = Member.objects.all()
    return render(request, 'adminpanel/reports.html', {
        'groups': groups,
        'admins': admins,
        'members': members,
    })

# ------------------------------ Notifications ------------------------------
@admin_required
def send_notification(request):
    admins = StaffProfile.objects.filter(role='group_admin')
    if request.method == 'POST':
        message_text = request.POST.get('message')
        selected_admins = request.POST.getlist('admins')
        if not message_text or not selected_admins:
            messages.error(request, "Message and admins are required")
            return redirect('adminpanel:send_notification')

        for admin_id in selected_admins:
            admin = get_object_or_404(StaffProfile, id=admin_id)
            SystemNotification.objects.create(message=message_text, target_admin=admin)

        messages.success(request, "Notification sent successfully")
        return redirect('adminpanel:send_notification')

    return render(request, 'adminpanel/send_notification.html', {'admins': admins})
