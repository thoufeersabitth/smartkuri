from django.utils import timezone


def get_subscription_status(subscription):

    """
    Returns subscription status with days and hours remaining.
    """

    if not subscription:
        return {
            'active': False,
            'days_left': 0,
            'hours_left': 0
        }

    # ✅ Unlimited / Free Plan
    if subscription.is_active and not subscription.end_date:
        return {
            'active': True,
            'days_left': "Unlimited",
            'hours_left': "Unlimited"
        }

    # ✅ Use date instead of datetime
    today = timezone.now().date()

    active = (
        subscription.is_active and
        subscription.end_date >= today
    )

    if active:

        delta = subscription.end_date - today

        days_left = delta.days

        hours_left = 24

    else:

        days_left = 0
        hours_left = 0

    return {
        'active': active,
        'days_left': days_left,
        'hours_left': hours_left
    }