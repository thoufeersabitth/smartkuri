from rest_framework import serializers
from payments.models import Payment


class PaymentSerializer(serializers.ModelSerializer):

    member_name = serializers.CharField(source="member.name", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)

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
        ]
