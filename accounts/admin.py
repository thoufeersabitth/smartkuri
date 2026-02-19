from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import StaffProfile

# -----------------------------
# Inline for StaffProfile inside User admin
# -----------------------------
class StaffProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    verbose_name_plural = 'Staff Profile'
    fk_name = 'user'
    # Only show Phone and Role in the inline, hide Group
    fields = ('phone', 'role')

# -----------------------------
# Extend default UserAdmin to include StaffProfile
# -----------------------------
class UserAdmin(BaseUserAdmin):
    inlines = (StaffProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_role')
    list_select_related = ('staffprofile',)

    def get_role(self, instance):
        if hasattr(instance, 'staffprofile'):
            return instance.staffprofile.role
        return None
    get_role.short_description = 'Role'

# -----------------------------
# Unregister default User admin and register custom one
# -----------------------------
admin.site.unregister(User)
admin.site.register(User, UserAdmin)

# -----------------------------
# Optional: Register StaffProfile separately
# -----------------------------
@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    # Show only Phone and Role (remove Group)
    list_display = ('user', 'phone', 'role')
    list_filter = ('role',)
    search_fields = ('user__username', 'phone', 'role')
    # fields = ('user', 'phone', 'role')  # optional: only editable fields
