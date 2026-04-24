# chitti/context_processors.py
from django.db.models import Sum
from payments.models import Payment

def group_admin_notifications(request):
    if request.user.is_authenticated:
   
        pending_payments = Payment.objects.filter(
            sent_to_admin=True,
            admin_status__iexact='pending', 
            is_seen=False
        )
        

        return {
            'total_pending_count': pending_payments.count(),
            'pending_total_amount': pending_payments.aggregate(Sum('amount'))['amount__sum'] or 0,
        }
    return {
        'total_pending_count': 0,
        'pending_total_amount': 0
    }