from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from accounts.models import StaffProfile
from members.models import Member

User = get_user_model()

class PhoneOrEmailBackend(ModelBackend):
    """
    Custom backend: login with username OR email OR phone
    Works for both staff and member accounts
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        user = None

        # 1️⃣ Try username
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            pass

        # 2️⃣ Try email
        if user is None:
            try:
                user = User.objects.get(email=username)
            except User.DoesNotExist:
                pass

        # 3️⃣ Try staff phone
        if user is None:
            staff = StaffProfile.objects.filter(phone=username).first()
            if staff:
                user = staff.user

        # 4️⃣ Try member phone
        if user is None:
            member = Member.objects.filter(phone=username).first()
            if member:
                user = member.user

        # 5️⃣ Check password
        if user and user.check_password(password):
            return user

        return None
