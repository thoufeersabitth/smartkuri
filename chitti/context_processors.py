# chitti/context_processors.py
from django.db.models import Sum, Q
from payments.models import Payment
from accounts.models import StaffProfile
from members.models import Member
from chitti.models import ChittiGroup, ChittiMember

def group_admin_notifications(request):
    if not request.user.is_authenticated:
        return {
            'total_pending_count': 0,
            'pending_total_amount': 0,
            'is_group_admin': False,
            'is_collector': False,
            'user_kuris': []
        }

    user = request.user

    # Notifications
    pending_payments = Payment.objects.filter(
        sent_to_admin=True,
        admin_status__iexact='pending', 
        is_seen=False
    )

    # 1. Check Group Admin Role
    is_group_admin = StaffProfile.objects.filter(
        Q(user=user) | Q(user__email=user.email) | Q(phone=user.username),
        role='group_admin'
    ).exists() or (hasattr(user, 'staffprofile') and user.staffprofile.role == 'group_admin')

    # 2. Check Collector Role
    is_collector = StaffProfile.objects.filter(
        Q(user=user) | Q(user__email=user.email) | Q(phone=user.username),
        role='collector'
    ).exists()

    # 3. Check Enrolled Kuris
    member_ids = list(Member.objects.filter(
        Q(user=user) | Q(email=user.email) | Q(phone=user.username)
    ).values_list('id', flat=True))

    group_ids = list(ChittiMember.objects.filter(
        member_id__in=member_ids
    ).values_list('group_id', flat=True))

    direct_group_ids = list(Member.objects.filter(
        id__in=member_ids,
        assigned_chitti_group__isnull=False
    ).values_list('assigned_chitti_group_id', flat=True))

    all_group_ids = list(set(group_ids + direct_group_ids))
    user_kuris = list(ChittiGroup.objects.filter(id__in=all_group_ids).distinct())

    return {
        'total_pending_count': pending_payments.count(),
        'pending_total_amount': pending_payments.aggregate(Sum('amount'))['amount__sum'] or 0,
        'is_group_admin': is_group_admin,
        'is_collector': is_collector,
        'user_kuris': user_kuris,
    }