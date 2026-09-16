from rest_framework import serializers
from members.models import Member


class AssignedMemberSerializer(serializers.ModelSerializer):
    group_id = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    monthly_amount = serializers.SerializerMethodField()
    duration_months = serializers.SerializerMethodField()
    collector_name = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            'id',
            'name',
            'phone',
            'group_id',
            'group_name',
            'monthly_amount',
            'duration_months',
            'collector_name',
        ]

    def _get_relevant_group(self, obj):
        request = self.context.get('request')
        if request and hasattr(request.user, 'staffprofile'):
            staff = request.user.staffprofile
            from collectors.api.v1.views import get_collector_groups
            assigned_groups = get_collector_groups(staff)

            # If member's primary group is in collector's assigned groups, use it
            if obj.assigned_chitti_group and obj.assigned_chitti_group in assigned_groups:
                return obj.assigned_chitti_group

            # Otherwise find the member's group that matches collector's assigned groups
            matched = obj.chitti_memberships.filter(group__in=assigned_groups).select_related('group').first()
            if matched and matched.group:
                return matched.group

        return obj.assigned_chitti_group

    def get_group_id(self, obj):
        grp = self._get_relevant_group(obj)
        return grp.id if grp else None

    def get_group_name(self, obj):
        grp = self._get_relevant_group(obj)
        return grp.name if grp else None

    def get_monthly_amount(self, obj):
        grp = self._get_relevant_group(obj)
        return float(grp.monthly_amount) if grp and grp.monthly_amount else 0.0

    def get_duration_months(self, obj):
        grp = self._get_relevant_group(obj)
        return grp.duration_months if grp else 0

    def get_collector_name(self, obj):
        grp = self._get_relevant_group(obj)
        if grp and grp.collector and grp.collector.user:
            return grp.collector.user.username
        return None
