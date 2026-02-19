from rest_framework import serializers
from django.contrib.auth.models import User
from subscriptions.models import SubscriptionPlan
from chitti.models import ChittiGroup
from members.models import Member
from accounts.models import StaffProfile

# ----------------------
# LOGIN
# ----------------------
class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

# ----------------------
# GROUP SIGNUP
# ----------------------
class GroupSignupSerializer(serializers.Serializer):
    group_name = serializers.CharField(max_length=255)
    phone = serializers.CharField(max_length=15)
    email = serializers.EmailField()
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    description = serializers.CharField(required=False, allow_blank=True)
    plan_id = serializers.IntegerField()

    def validate(self, data):
        if data['password1'] != data['password2']:
            raise serializers.ValidationError("Passwords do not match")
        if ChittiGroup.objects.filter(name=data['group_name']).exists():
            raise serializers.ValidationError("Group name already exists")
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError("Email already registered")
        return data

# ----------------------
# OTP VERIFY
# ----------------------
class OTPVerifySerializer(serializers.Serializer):
    otp = serializers.CharField()

# ----------------------
# PASSWORD RESET REQUEST
# ----------------------
class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField()

# ----------------------
# PASSWORD RESET CONFIRM
# ----------------------
class PasswordResetConfirmSerializer(serializers.Serializer):
    otp = serializers.CharField()
    password1 = serializers.CharField()
    password2 = serializers.CharField()

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
            raise serializers.ValidationError("Passwords do not match")
        if User.objects.filter(username=data['username']).exists():
            raise serializers.ValidationError("Username is already taken")
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError("Email is already registered")
        if self.admin_user:
            if not ChittiGroup.objects.filter(id=data['group_id'], owner=self.admin_user).exists():
                raise serializers.ValidationError("Invalid group selection")
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
        if self.admin_user and not ChittiGroup.objects.filter(id=value, owner=self.admin_user).exists():
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
    role = serializers.ChoiceField(choices=['admin','collector','group_admin'])
