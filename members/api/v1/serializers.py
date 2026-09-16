from rest_framework import serializers
from members.models import Member
from chitti.models import ChittiMember
from payments.models import Payment


from django.contrib.auth.models import User


class MemberSerializer(serializers.ModelSerializer):
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)

    group_name = serializers.SerializerMethodField()
    group_id = serializers.SerializerMethodField()
    monthly_amount = serializers.SerializerMethodField()

    aadhaar_masked = serializers.SerializerMethodField()

    def _get_relevant_group(self, obj):
        # 1. Explicit group in context
        ctx_group = self.context.get("group")
        if ctx_group:
            return ctx_group

        # 2. group_id in context or request query params
        request = self.context.get("request")
        group_id = self.context.get("group_id")
        if not group_id and request:
            group_id = request.query_params.get("group_id") or request.GET.get("group_id")

        if group_id:
            try:
                gid = int(group_id)
                cm = obj.chitti_memberships.filter(group_id=gid).select_related("group").first()
                if cm and cm.group:
                    return cm.group
                if obj.assigned_chitti_group_id == gid:
                    return obj.assigned_chitti_group
            except (ValueError, TypeError):
                pass

        # 3. If caller is Group Admin, prefer group owned by this admin
        if request and request.user and request.user.is_authenticated:
            admin_membership = obj.chitti_memberships.filter(group__owner=request.user).select_related("group").first()
            if admin_membership and admin_membership.group:
                return admin_membership.group
            if obj.assigned_chitti_group and obj.assigned_chitti_group.owner == request.user:
                return obj.assigned_chitti_group

        # 4. Fallback to assigned_chitti_group
        if obj.assigned_chitti_group:
            return obj.assigned_chitti_group

        # 5. Fallback to any active membership
        first_membership = obj.chitti_memberships.filter(group__is_active=True).select_related("group").first()
        if first_membership and first_membership.group:
            return first_membership.group

        any_membership = obj.chitti_memberships.select_related("group").first()
        if any_membership and any_membership.group:
            return any_membership.group

        return None

    def get_group_name(self, obj):
        group = self._get_relevant_group(obj)
        return group.name if group else ""

    def get_group_id(self, obj):
        group = self._get_relevant_group(obj)
        return group.id if group else 0

    def get_monthly_amount(self, obj):
        group = self._get_relevant_group(obj)
        return float(group.monthly_amount) if (group and group.monthly_amount) else 0.0

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
            "monthly_amount",
            "address",          
            "join_date",        
            "aadhaar_masked",  
        ]

    def get_aadhaar_masked(self, obj):
        if obj.aadhaar_no:
            return "XXXX-XXXX-" + obj.aadhaar_no[-4:]
        return None

class MemberCreateSerializer(serializers.ModelSerializer):
    phone = serializers.CharField(required=True, min_length=10, max_length=15)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True
    )
    existing_user_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        write_only=True
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
            "existing_user_id",
        ]

    def validate_assigned_chitti_group(self, group):
        request = self.context.get("request")
        if group and request and group.owner != request.user:
            raise serializers.ValidationError(
                "You can add members only to your own groups"
            )
        return group

    def validate(self, data):
        phone = data.get("phone", "").strip()
        email = data.get("email", "").strip()
        existing_user_id = data.get("existing_user_id")
        password = data.get("password")

        if not phone:
            raise serializers.ValidationError({"phone": "Mobile number is mandatory."})
        if not email:
            raise serializers.ValidationError({"email": "Email address is mandatory."})

        # 🛡️ Strict: Phone must never contain '@' or letters (digits only)
        if "@" in phone or not phone.isdigit() or len(phone) < 10:
            raise serializers.ValidationError({
                "phone": "Phone number must be a valid 10-digit number (emails or letters are strictly not allowed)."
            })

        # 🛡️ Strict: Email must contain '@' and '.'
        if "@" not in email or "." not in email:
            raise serializers.ValidationError({
                "email": "Please enter a valid email address."
            })

        # Fresh member registration checks (when NOT explicitly enrolling an existing member)
        if not existing_user_id:
            # Check if phone already belongs to an existing member/user
            if Member.objects.filter(phone=phone).exists() or User.objects.filter(username=phone).exists():
                raise serializers.ValidationError({
                    "phone": f"Mobile number '{phone}' is already registered with an existing member. Please tap Auto-Fill to enrol this member or enter a unique mobile number."
                })
            # Check if email already belongs to an existing member/user
            if Member.objects.filter(email__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
                raise serializers.ValidationError({
                    "email": f"Email '{email}' is already registered with an existing member. Please tap Auto-Fill to enrol this member or enter a unique email address."
                })
            # Password validation for fresh registration
            if not password or len(password) < 6:
                raise serializers.ValidationError({
                    "password": "Password (minimum 6 characters) is required for new member registration."
                })
        else:
            # Enrolling existing member: ensure the phone/email doesn't collide with ANOTHER member
            if Member.objects.filter(phone=phone).exclude(user_id=existing_user_id).exists():
                raise serializers.ValidationError({
                    "phone": f"Mobile number '{phone}' is already registered with another member."
                })
            if Member.objects.filter(email__iexact=email).exclude(user_id=existing_user_id).exists():
                raise serializers.ValidationError({
                    "email": f"Email '{email}' is already registered with another member."
                })

        return data

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
