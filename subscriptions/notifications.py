import logging
from django.utils import timezone
from accounts.models import StaffProfile
from chitti.models import ChittiGroup
from subscriptions.models import GroupSubscription, SubscriptionPlan, SubscriptionNotificationLog
from core.fcm_service import send_push_to_user

logger = logging.getLogger(__name__)


def check_and_send_subscription_reminders(target_user=None):
    """
    Evaluates subscription status and sends automated FCM push notifications for:
      - 2 days left (Warning)
      - 1 day left (Urgent Warning)
      - Expired (Upgrade Request)
    
    Can run for all group admins or a single target_user.
    Deduplicates using SubscriptionNotificationLog so no duplicate push is sent on the same day.
    Returns: int (number of push notifications dispatched)
    """
    if target_user:
        admins = StaffProfile.objects.filter(user=target_user, role='group_admin')
    else:
        admins = StaffProfile.objects.filter(role='group_admin')

    sent_count = 0
    today = timezone.now().date()
    now = timezone.now()

    for admin in admins:
        user = admin.user

        # Find main group & subscription
        groups = ChittiGroup.objects.filter(owner=user)
        if not groups.exists() and not getattr(admin, 'is_subscribed', False):
            continue
        main_group = groups.filter(parent_group__isnull=True).first()

        sub = getattr(main_group, 'subscription', None) if main_group else None

        plan_name = 'Free Trial'
        is_trial = True
        days_left = 0

        if sub:
            plan_name = sub.plan.name
            is_trial = (
                sub.plan.price == 0 or
                'trial' in sub.plan.name.lower() or
                'free' in sub.plan.name.lower()
            )
            if sub.end_date:
                delta = sub.end_date - now
                if sub.end_date < now:
                    days_left = -1
                else:
                    days_left = delta.days
            else:
                days_left = sub.plan.duration_days
        elif getattr(admin, 'is_subscribed', False) and admin.subscription_end:
            # Paid Pro plan recorded directly on StaffProfile
            pro_p = getattr(admin, 'subscription_plan', None)
            plan_name = pro_p.name if pro_p else 'SmartKuri Pro'
            is_trial = False
            delta_days = (admin.subscription_end - today).days
            days_left = delta_days if delta_days >= 0 else -1
        else:
            # Free Trial based on user signup date (7 days)
            free_plan = SubscriptionPlan.objects.filter(name='Free Trial', is_active=True).first()
            duration = free_plan.duration_days if free_plan else 7
            days_passed = (now - user.date_joined).days
            days_left = duration - days_passed
            plan_name = free_plan.name if free_plan else 'Free Trial'
            is_trial = True

        # Determine notification milestone
        milestone = None
        title = ""
        body = ""

        # 7-day advance notice for paid Pro plans
        if not is_trial and days_left == 7:
            milestone = '7_days_left'
            title = f"⏳ {plan_name}: 7 Days Remaining"
            body = f"Your {plan_name} subscription expires in 7 days. Tap to renew now for uninterrupted access."

        elif days_left == 2:
            milestone = '2_days_left'
            if is_trial:
                title = "⏳ Free Trial: 2 Days Left!"
                body = "Your 7-Day Free Trial ends in 2 days. Upgrade to SmartKuri Pro now to keep adding members and groups."
            else:
                title = f"⏳ {plan_name}: 2 Days Left!"
                body = f"Your {plan_name} subscription will expire in 2 days. Tap to renew now."

        elif days_left == 1:
            milestone = '1_day_left'
            if is_trial:
                title = "⚠️ Free Trial Expiring Tomorrow!"
                body = "Only 24 hours remaining on your Free Trial. Upgrade to Pro now to ensure uninterrupted access."
            else:
                title = f"⚠️ {plan_name} Expiring Tomorrow!"
                body = f"Your {plan_name} subscription expires in 24 hours. Tap to renew and avoid disruptions."

        elif days_left <= 0:
            milestone = 'expired'
            if is_trial:
                title = "🚨 Free Trial Expired!"
                body = "Your SmartKuri Free Trial has expired. Upgrade to Pro to continue adding members and groups."
            else:
                title = f"🚨 {plan_name} Expired!"
                body = f"Your {plan_name} plan has expired. Upgrade or renew now to restore full features."


        if not milestone:
            continue

        # Check if already sent today for this milestone
        already_sent = SubscriptionNotificationLog.objects.filter(
            user=user,
            notification_type=milestone,
            sent_date=today
        ).exists()

        if already_sent:
            continue

        # Dispatch FCM push
        push_sent = send_push_to_user(
            user=user,
            title=title,
            body=body,
            data={
                "type": "subscription",
                "action": "upgrade",
                "plan": plan_name,
                "days_left": str(max(days_left, 0)),
                "milestone": milestone,
            }
        )

        # Log into database to guarantee idempotence
        SubscriptionNotificationLog.objects.create(
            user=user,
            subscription=sub,
            notification_type=milestone,
            sent_date=today
        )

        logger.info(f"Subscription reminder ({milestone}) sent to {user.username} (FCM delivered: {push_sent})")
        sent_count += 1

    return sent_count
