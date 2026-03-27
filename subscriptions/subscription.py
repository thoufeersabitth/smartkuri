from django.utils import timezone

def get_subscription_status(subscription):
    """
    Returns subscription status with days and hours remaining.
    """

    if not subscription:
        return {'active': False, 'days_left': 0, 'hours_left': 0}

    # Free plan or unlimited plan (no expiry)
    if subscription.is_active and not subscription.end_date:
        return {
            'active': True,
            'days_left': "Unlimited",
            'hours_left': "Unlimited"
        }

    now = timezone.now()
    active = subscription.end_date >= now

    if active:
        delta = subscription.end_date - now
        days_left = delta.days
        hours_left = delta.seconds // 3600
    else:
        days_left = 0
        hours_left = 0

    return {
        'active': active,
        'days_left': days_left,
        'hours_left': hours_left
    }