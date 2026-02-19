# adminpanel/utils.py
from builtins import hasattr
from django.shortcuts import redirect

def admin_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not hasattr(request.user, 'staffprofile') or request.user.staffprofile.role != 'admin':
            return redirect('no_access')  # simple 403 page or redirect
        return view_func(request, *args, **kwargs)
    return wrapper
