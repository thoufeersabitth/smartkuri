from functools import wraps
from django.shortcuts import redirect
from members.models import Member


# -----------------------------
# ROLE BASED DECORATOR (STAFF)
# -----------------------------
def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('accounts:login')

            if hasattr(request.user, 'staffprofile'):
                role = request.user.staffprofile.role

                if role in allowed_roles:
                    return view_func(request, *args, **kwargs)

                # Redirect to own dashboard
                if role == 'admin':
                    return redirect('accounts:admin_dashboard')
                elif role == 'collector':
                    return redirect('accounts:collector_dashboard')
                elif role == 'group_admin':
                    return redirect('accounts:group_admin_dashboard')

            return redirect('accounts:login')
        return _wrapped_view
    return decorator


admin_required = role_required('admin')
collector_required = role_required('collector')
group_admin_required = role_required('group_admin')


# -----------------------------
# MEMBER DECORATOR (FIXED)
# -----------------------------
def member_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')

        # ✅ CORRECT CHECK
        if Member.objects.filter(user=request.user).exists():
            return view_func(request, *args, **kwargs)

        return redirect('accounts:login')
    return _wrapped_view
