import re
from rest_framework import serializers
from accounts.models import StaffProfile
from chitti.models import ChittiGroup, ChittiMember, Auction
from datetime import date
from dateutil.relativedelta import relativedelta
from rest_framework import serializers
from chitti.models import ChittiGroup



class ChittiGroupSerializer(serializers.ModelSerializer):

    start_date = serializers.DateField(
        format="%d-%m-%Y",                # Output format
        input_formats=["%d-%m-%Y", "%Y-%m-%d"]  # Accept both while editing
    )

    end_date_calculated = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = ChittiGroup
        fields = [
            'id',
            'name',
            'monthly_amount',
            'duration_months',
            'total_amount',
            'start_date',
            'parent_group',
            'end_date_calculated',
            'is_expired',
        ]
        read_only_fields = [
            'total_amount',
            'parent_group',
            'end_date_calculated',
            'is_expired'
        ]


    def get_end_date_calculated(self, obj):
        if obj.start_date and obj.duration_months:
            end_date = obj.start_date + relativedelta(months=obj.duration_months)
            return end_date.strftime("%d-%m-%Y")
        return None

    def get_is_expired(self, obj):
        if obj.start_date and obj.duration_months:
            end_date = obj.start_date + relativedelta(months=obj.duration_months)
            return date.today() > end_date
        return False

class ChittiMemberSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="member.name", read_only=True)
    phone = serializers.CharField(source="member.phone", read_only=True)

    member_status = serializers.CharField(read_only=True)
    total_paid = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )
    pending_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        read_only=True
    )

    class Meta:
        model = ChittiMember
        fields = [
            "id",
            "token_no",
            "name",
            "phone",
            "member_status",
            "total_paid",
            "pending_amount",
        ]



class AuctionSerializer(serializers.ModelSerializer):
    winner_token = serializers.IntegerField(
        source="winner.token_no",
        read_only=True
    )
    winner_name = serializers.CharField(
        source="winner.member.name",
        read_only=True
    )

    # 🔹 Computed fields
    status = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()

    class Meta:
        model = Auction
        fields = [
            "id",
            "group",
            "month_no",
            "auction_date",
            "winner",
            "winner_token",
            "winner_name",
            "status",
            "action",
        ]

    # -------------------------
    # STATUS LOGIC
    # -------------------------
    def get_status(self, obj):
        today = date.today()

        if obj.is_closed:
            return "Completed"
        elif obj.auction_date == today:
            return "Today"
        else:
            return "Upcoming"

    # -------------------------
    # ACTION LOGIC
    # -------------------------
    def get_action(self, obj):
        if obj.is_closed:
            return "View"
        else:
            return "Spin"

    # -------------------------
    # VALIDATION (create time)
    # -------------------------
    def validate(self, data):
        group = data.get("group")
        month_no = data.get("month_no")

        if Auction.objects.filter(
            group=group,
            month_no=month_no
        ).exists():
            raise serializers.ValidationError(
                f"Auction already exists for month {month_no}"
            )

        return data
    


class CashCollectorCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    existing_user_id = serializers.IntegerField(required=False, allow_null=True)
    group = serializers.PrimaryKeyRelatedField(
        queryset=ChittiGroup.objects.all(),
        required=False,
        allow_null=True
    )

    def validate_group(self, group):
        if not group:
            return group
        request = self.context["request"]
        if group.owner != request.user:
            raise serializers.ValidationError(
                "You can assign collectors only to your own groups"
            )
        return group

    def validate(self, data):
        phone = data.get("phone", "").strip() if data.get("phone") else ""
        email = data.get("email", "").strip() if data.get("email") else ""

        if "@" in phone:
            raise serializers.ValidationError({
                "phone": "Phone number cannot contain '@'. Enter a valid 10-digit mobile number."
            })
        digits = re.sub(r'\D', '', phone)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            digits = digits[1:]
        if len(digits) != 10:
            raise serializers.ValidationError({
                "phone": "Please enter a valid 10-digit mobile number."
            })
        data["phone"] = digits

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise serializers.ValidationError({
                "email": "Please enter a valid email address (e.g. name@gmail.com)."
            })

        return data


class CashCollectorListSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email")
    status = serializers.BooleanField(source="user.is_active") 
    group_name = serializers.CharField(
        source="assigned_chitti_groups.first.name",
        read_only=True
    )

    class Meta:
        model = StaffProfile
        fields = [
            "id",
            "username",
            "email",
            "phone",
            "group_name",
            "status",  
        ]



class CashCollectorUpdateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", required=False)
    username = serializers.CharField(source="user.username", required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = StaffProfile
        fields = ["phone", "email", "username", "password"]  

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        new_password = validated_data.pop("password", None)

        # ✅ Update email
        if "email" in user_data:
            instance.user.email = user_data["email"]

        # ✅ Update username
        if "username" in user_data:
            instance.user.username = user_data["username"]

        # ✅ Update password if provided
        if new_password and str(new_password).strip():
            instance.user.set_password(str(new_password).strip())

        instance.user.save()

        return super().update(instance, validated_data)
