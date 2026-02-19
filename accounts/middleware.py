# accounts/middleware.py
from django.shortcuts import redirect
from django.urls import reverse
from members.models import Member

class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        # Not logged in → allow
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Allowed paths
        allowed_paths = [
            reverse('accounts:login'),
            reverse('accounts:logout'),
            reverse('accounts:change_password'),
        ]

        if request.path in allowed_paths or request.path.startswith('/static/'):
            return self.get_response(request)

        # Check member
        member = Member.objects.filter(user=request.user).first()
        if not member:
            return self.get_response(request)

        # Force password change only once
        if member.is_first_login:
            return redirect('accounts:change_password')

        return self.get_response(request)
