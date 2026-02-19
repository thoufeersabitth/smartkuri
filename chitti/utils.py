from django.db.models import Sum
from dateutil.relativedelta import relativedelta



def currency(amount):
    """
    Convert a numeric value to Indian Rupees format (₹).
    Example: 12345.67 -> ₹12,345.67
    """
    try:
        amount = float(amount)
        return f"₹{amount:,.2f}"
    except (ValueError, TypeError):
        return "₹0.00"

def get_month_index(group, year, month):
    return (
        (year - group.start_date.year) * 12
        + (month - group.start_date.month)
        + 1
    )




def get_member_month_status(chitti_member, year, month):
    from payments.models import Payment  # circular avoid

    group = chitti_member.group
    month_index = get_month_index(group, year, month)

    if month_index < 1 or month_index > group.duration_months:
        return None

    paid = Payment.objects.filter(
        member=chitti_member.member,
        group=group,
        paid_date__year=year,
        paid_date__month=month,
        payment_status='success'
    ).aggregate(total=Sum('amount'))['total'] or 0

    if paid >= group.monthly_amount:
        status = "Completed"
    else:
        status = "Pending"

    return {
        'month_index': month_index,
        'paid': paid,
        'due': max(group.monthly_amount - paid, 0),
        'status': status
    }


def get_full_rotation(chitti_member):
    group = chitti_member.group
    result = []

    current = group.start_date

    for _ in range(group.duration_months):
        status = get_member_month_status(
            chitti_member,
            current.year,
            current.month
        )
        if status:
            result.append({
                'month': current.strftime('%B %Y'),
                **status
            })
        current += relativedelta(months=1)

    return result
