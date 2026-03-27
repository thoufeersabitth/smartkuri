from rest_framework import serializers
from payments.models import Payment

class PaymentSerializer(serializers.ModelSerializer):

    member_name = serializers.CharField(source="member.name", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)
    collected_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "group",
            "group_name",
            "member",
            "member_name",
            "amount",
            "paid_date",
            "payment_method",
            "payment_status",
            "collected_by_name",
        ]

    def get_collected_by_name(self, obj):
        if not obj.collected_by:
            return "Admin"

        role = obj.collected_by.role

        if role in ["group_admin", "admin"]:
            return "Admin"

        if role == "collector":
            return obj.collected_by.user.username

        return "Admin"
