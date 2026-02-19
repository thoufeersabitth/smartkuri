from rest_framework import serializers
from members.models import Member


class AssignedMemberSerializer(serializers.ModelSerializer):
    group_name = serializers.CharField(
        source='assigned_chitti_group.name',
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
            'group_name',
            'collector_name',
        ]
