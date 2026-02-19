# accounts/middleware.py
from django.shortcuts import redirect
from django.urls import reverse
from members.models import Member

class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only for authenticated users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Ignore static & media
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return self.get_response(request)

        # Allow logout and change-password
        allowed_paths = [
            reverse('accounts:logout'),
            reverse('accounts:change_password')
        ]

        try:
            member = Member.objects.get(user=request.user)
        except Member.DoesNotExist:
            return self.get_response(request)

        # Force first-time password change only if not on allowed pages
        if member.is_first_login and request.path not in allowed_paths:
            return redirect('accounts:change_password')

        return self.get_response(request)
