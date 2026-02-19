from builtins import hasattr
from django.utils import timezone
from .models import GroupSubscription


def close_expired_subscriptions():
    """
    Expired subscriptions automatic ayi close cheyyum
    """
    return GroupSubscription.objects.filter(
        is_active=True,
        end_date__lte=timezone.now()
    ).update(is_active=False)


def has_active_subscription(group):
    """
    Safe read-only check
    """
    if not hasattr(group, 'subscription'):
        return False
    return group.subscription.is_current()
