from django.utils import timezone
from chitti.models import ChittiGroup


# ---------------- Effective Subscription ----------------
def get_effective_subscription(group: ChittiGroup):
    """
    Returns active subscription from main group.
    Sub-groups inherit subscription from parent group.
    """
    if not group:
        return None

    main_group = group.parent_group or group
    subscription = getattr(main_group, "subscription", None)

    if not subscription:
        return None

    # If subscription has method is_current(), use it safely
    if hasattr(subscription, "is_current"):
        if not subscription.is_current():
            return None

    return subscription


# ---------------- Subscription Status ----------------
def get_subscription_status(subscription):
    """
    Returns subscription status with days and hours left.
    Handles free/unlimited plans (no end_date).
    """
    if not subscription:
        return {"active": False, "days_left": 0, "hours_left": 0}

    # Free / unlimited plan
    if not subscription.end_date:
        return {
            "active": True,
            "days_left": subscription.plan.duration_days or 0,
            "hours_left": 0
        }

    now = timezone.now()
    end = subscription.end_date
    active = end >= now

    if active:
        delta = end - now
        days_left = delta.days
        hours_left = delta.seconds // 3600

        # Ensure at least 1 hour on last moment
        if days_left == 0 and hours_left == 0:
            hours_left = 1
    else:
        days_left = 0
        hours_left = 0

    return {
        "active": active,
        "days_left": days_left,
        "hours_left": hours_left
    }


# ---------------- Human-readable Time Left ----------------
def get_time_left(subscription):
    """
    Returns human-readable time left.
    """
    status = get_subscription_status(subscription)

    if not status["active"]:
        return "0"

    days = status["days_left"]
    hours = status["hours_left"]

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
    subscription = get_effective_subscription(group)

    if not subscription:
        return False

    current_members = group.chitti_members.count()
    max_members = subscription.plan.max_members or 0

    return current_members < max_members


# ---------------- Group Creation Limit Check ----------------
def can_create_group(admin_user) -> bool:
    if not admin_user:
        return False

    main_group = ChittiGroup.objects.filter(
        owner=admin_user,
        parent_group__isnull=True
    ).first()

    subscription = get_effective_subscription(main_group)
    if not subscription:
        return False

    max_groups = subscription.plan.max_groups or 0

    total_groups = ChittiGroup.objects.filter(
        owner=admin_user
    ).count()

    return total_groups < max_groups