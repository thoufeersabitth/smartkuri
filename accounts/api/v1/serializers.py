import re
from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from subscriptions.models import SubscriptionPlan
from chitti.models import ChittiGroup


# ----------------------
# LOGIN
# ----------------------
class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

class GroupSignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=15)
    email = serializers.EmailField()
    # Match these to your JSON keys
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        # Use the updated keys here
        if data.get('password') != data.get('confirm_password'):
            raise serializers.ValidationError({"password": "Passwords do not match"})
        
        email = data.get('email', '').strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise serializers.ValidationError({"email": "Please enter a valid email address (e.g. name@gmail.com)."})

        phone = data.get('phone', '').strip()
        if "@" in phone:
            raise serializers.ValidationError({"phone": "Phone number cannot contain '@'. Enter a valid 10-digit mobile number."})

        digits = re.sub(r'\D', '', phone)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            digits = digits[1:]
        if len(digits) != 10:
            raise serializers.ValidationError({"phone": "Please enter a valid 10-digit mobile number."})
        data['phone'] = digits

        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError({"email": "Email is already registered"})
            
        return data

# ----------------------
# OTP VERIFY
# ----------------------
class OTPVerifySerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=6)


# ----------------------
# PASSWORD RESET REQUEST
# ----------------------
class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField()


# ----------------------
# PASSWORD RESET CONFIRM
# ----------------------
class PasswordResetConfirmSerializer(serializers.Serializer):
    otp = serializers.CharField(max_length=6)
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["password1"] != data["password2"]:
            raise serializers.ValidationError(
                {"password": "Passwords do not match"}
            )

        validate_password(data["password1"])
        return data


# ----------------------
# CASH COLLECTOR CREATE
# ----------------------
class CashCollectorCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    group_id = serializers.IntegerField()

    def __init__(self, *args, **kwargs):
        self.admin_user = kwargs.pop('admin_user', None)
        super().__init__(*args, **kwargs)

    def validate(self, data):

        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError(
                {"password": "Passwords do not match"}
            )

        validate_password(data["password"])

        if User.objects.filter(username=data['username']).exists():
            raise serializers.ValidationError(
                {"username": "Username is already taken"}
            )

        email = data.get('email', '').strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise serializers.ValidationError({"email": "Please enter a valid email address (e.g. name@gmail.com)."})

        phone = data.get('phone', '').strip()
        if "@" in phone:
            raise serializers.ValidationError({"phone": "Phone number cannot contain '@'. Enter a valid 10-digit mobile number."})

        digits = re.sub(r'\D', '', phone)
        if digits.startswith('91') and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            digits = digits[1:]
        if len(digits) != 10:
            raise serializers.ValidationError({"phone": "Please enter a valid 10-digit mobile number."})
        data['phone'] = digits

        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                {"email": "Email is already registered"}
            )

        if self.admin_user:
            if not ChittiGroup.objects.filter(
                id=data['group_id'],
                owner=self.admin_user
            ).exists():
                raise serializers.ValidationError(
                    {"group_id": "Invalid group selection"}
                )

        return data


# ----------------------
# CASH COLLECTOR EDIT
# ----------------------
class CashCollectorEditSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, read_only=True)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    group_id = serializers.IntegerField()

    def __init__(self, *args, **kwargs):
        self.admin_user = kwargs.pop('admin_user', None)
        super().__init__(*args, **kwargs)

    def validate_group_id(self, value):
        if self.admin_user and not ChittiGroup.objects.filter(
            id=value,
            owner=self.admin_user
        ).exists():
            raise serializers.ValidationError("Invalid group selection")
        return value


# ----------------------
# ADD ADMIN
# ----------------------
class AddAdminSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=15)
    password = serializers.CharField(write_only=True)
    role = serializers.ChoiceField(
        choices=['admin', 'collector', 'group_admin']
    )


# ----------------------
# SUBSCRIPTION PLAN SERIALIZER
# ----------------------
class SubscriptionPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "price",
            "duration_days",
            "max_members",
            "max_groups",
            "is_active",
        ]