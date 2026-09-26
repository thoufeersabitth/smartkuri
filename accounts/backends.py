import re
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q
from accounts.models import StaffProfile
from members.models import Member

User = get_user_model()


class PhoneOrEmailBackend(ModelBackend):
    """
    Custom backend: login with username OR email OR phone.
    Works for both staff and member accounts.
    Tests all candidate users matching the identifier and returns the one whose
    password matches. Respects target_role if specified.
    """
    def authenticate(self, request, username=None, password=None, target_role=None, **kwargs):
        if username is None or password is None:
            return None

        clean_id = str(username).strip()
        target_role = target_role or kwargs.get('target_role') or kwargs.get('role')

        candidate_users = []

        def _add_user(u):
            if u and u not in candidate_users:
                candidate_users.append(u)

        # 1. Exact or case-insensitive username match
        for u in User.objects.filter(Q(username__iexact=clean_id) | Q(username=clean_id)):
            _add_user(u)

        # 2. Email match
        for u in User.objects.filter(email__iexact=clean_id):
            _add_user(u)

        # 3. StaffProfile phone match
        for sp in StaffProfile.objects.filter(phone=clean_id).select_related('user'):
            _add_user(sp.user)

        # 4. Member phone match
        for m in Member.objects.filter(phone=clean_id).select_related('user'):
            _add_user(m.user)

        # 5. Last 10 digits match for phone
        digits = re.sub(r'\D', '', clean_id)
        if len(digits) >= 10:
            last10 = digits[-10:]
            for sp in StaffProfile.objects.filter(phone__endswith=last10).select_related('user'):
                _add_user(sp.user)
            for m in Member.objects.filter(phone__endswith=last10).select_related('user'):
                _add_user(m.user)

        # If target_role is specified, prioritize candidates with that role
        if target_role:
            tr = str(target_role).lower().strip()
            if tr in ['group_admin', 'admin']:
                candidate_users.sort(
                    key=lambda u: 0 if getattr(getattr(u, 'staffprofile', None), 'role', '') in ['group_admin', 'admin'] else 1
                )
            elif tr == 'collector':
                candidate_users.sort(
                    key=lambda u: 0 if getattr(getattr(u, 'staffprofile', None), 'role', '') == 'collector' else 1
                )
            elif tr == 'member':
                candidate_users.sort(
                    key=lambda u: 0 if hasattr(u, 'member_profile') else 1
                )

        # Check password for each candidate
        for u in candidate_users:
            if u.is_active and (u.check_password(password) or u.check_password(str(password).strip())):
                return u

        return None

