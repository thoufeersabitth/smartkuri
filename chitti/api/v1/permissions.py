from rest_framework.permissions import BasePermission

class IsGroupAdmin(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            hasattr(request.user, 'staffprofile') and
            request.user.staffprofile.role == 'group_admin'
        )
