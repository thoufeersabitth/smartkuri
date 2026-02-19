from rest_framework import serializers
from members.models import Member
from chitti.models import ChittiMember
from payments.models import Payment


class MemberSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    group_name = serializers.CharField(
        source="assigned_chitti_group.name",
        read_only=True
    )
    group_id = serializers.IntegerField(
        source="assigned_chitti_group.id",
        read_only=True
    )

    class Meta:
        model = Member
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "is_active",     
            "group_id",      
            "group_name",    
        ]


class MemberCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=6
    )

    class Meta:
        model = Member
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "aadhaar_no",
            "assigned_chitti_group",
            "password",
        ]

    def validate_assigned_chitti_group(self, group):
        request = self.context.get("request")

        if group.owner != request.user:
            raise serializers.ValidationError(
                "You can add members only to your own groups"
            )
        return group
class MemberUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Member
        fields = [
            "name",
            "email",
            "phone",
            "address",
            "aadhaar_no",
            "assigned_chitti_group",
        ]

    def validate_assigned_chitti_group(self, group):
        request = self.context.get("request")

        if group.owner != request.user:
            raise serializers.ValidationError(
                "You can assign only your own groups"
            )
        return group
