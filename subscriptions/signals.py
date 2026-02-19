from django.utils import timezone
from chitti.models import ChittiGroup, ChittiMember
from subscription.models import SubscriptionPlan, GroupSubscription
from subscription.utils import can_add_member

# 1️⃣ Create a new group with subscription
def create_group(admin_user, group_name, plan_name):
    plan = SubscriptionPlan.objects.get(name=plan_name)
    group = ChittiGroup.objects.create(
        name=group_name,
        owner=admin_user,
        total_amount=plan.price,
        monthly_amount=plan.monthly_amount,
        duration_months=plan.duration_days // 30,
        start_date=timezone.now().date(),
        is_active=True
    )
    GroupSubscription.objects.create(group=group, plan=plan).activate()
    return group

# 2️⃣ Add member to separate group
def add_member_to_group(group, member, token_no):
    if not can_add_member(group):
        return False, f"Cannot add member: limit reached ({group.subscription.plan.max_members}) or expired"

    ChittiMember.objects.create(
        group=group,
        member=member,
        token_no=token_no
    )
    return True, "Member added successfully"
