from rest_framework import serializers
from members.models import Member


class AssignedMemberSerializer(serializers.ModelSerializer):
    group_id = serializers.IntegerField(
        source='assigned_chitti_group.id',
        read_only=True
    )
    group_name = serializers.CharField(
        source='assigned_chitti_group.name',
        read_only=True
    )
    monthly_amount = serializers.FloatField(
        source='assigned_chitti_group.monthly_amount',
        read_only=True
    )
    duration_months = serializers.IntegerField(
        source='assigned_chitti_group.duration_months',
        read_only=True
    )
    collector_name = serializers.CharField(
        source='assigned_chitti_group.collector.user.username',
        read_only=True
    )

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
