from django.utils import timezone
from chitti.models import ChittiGroup

def get_effective_subscription(group: ChittiGroup):
    """
    Returns active subscription from main group.
    Sub-groups inherit subscription from parent group.
    """
    if not group:
        return None

    main_group = group.parent_group or group
    subscription = getattr(main_group, 'subscription', None)

    if not subscription or not subscription.is_current():
        return None

    return subscription


# ---------------- Subscription Status ----------------
def get_subscription_status(subscription):
    """
    Returns a dict with active status, days left, and hours left.
    Handles last day correctly.
    """
    if not subscription or not subscription.end_date:
        return {'active': False, 'days_left': 0, 'hours_left': 0}

    now = timezone.now()
    end = subscription.end_date
    active = end >= now

    if active:
        delta = end - now
        days_left = delta.days
        hours_left = delta.seconds // 3600

        # If less than 1 day but hours > 0, show hours
        if days_left == 0 and hours_left == 0:
            hours_left = 1
    else:
        days_left = 0
        hours_left = 0

    return {
        'active': active,
        'days_left': days_left,
        'hours_left': hours_left
    }


# ---------------- Human-readable Time Left ----------------
def get_time_left(subscription):
    """
    Returns human-readable string for subscription time left.
    Examples:
        "2 days", "1 day", "Expires in 12 hours", "Expires today"
    """
    status = get_subscription_status(subscription)

    if not status['active']:
        return "0"

    days = status['days_left']
    hours = status['hours_left']

    if days > 1:
        return f"{days} days"
    elif days == 1:
        return "1 day"
    elif hours > 1:
        return f"Expires in {hours} hours"
    elif hours == 1:
        return "Expires in 1 hour"
    else:
        return "Expires today"


# ---------------- Member Limit Check ----------------
def can_add_member(group: ChittiGroup) -> bool:
    """
    Checks whether a new member can be added to the group
    based on the effective subscription (main group subscription).
    """
    subscription = get_effective_subscription(group)

    if not subscription:
        return False

    current_members = group.chitti_members.count()
    return current_members < subscription.plan.max_members


# ---------------- Group Creation Limit Check ----------------
def can_create_group(admin_user) -> bool:
    """
    admin_user MUST be User instance
    """
    if not admin_user:
        return False

    main_group = ChittiGroup.objects.filter(
        owner=admin_user,
        parent_group__isnull=True
    ).first()

    subscription = get_effective_subscription(main_group)
    if not subscription:
        return False

    plan = subscription.plan

    total_groups = ChittiGroup.objects.filter(
        owner=admin_user
    ).count()

    return total_groups < plan.max_groups
