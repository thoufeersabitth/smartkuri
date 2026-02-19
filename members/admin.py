from django.contrib import admin
from .models import Member

@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'phone',
        'email',
        'assigned_chitti_group',
        'verification_status',
        'user',
    )
    search_fields = ('name', 'phone', 'email')
    list_filter = ('assigned_chitti_group',)

    # 🔹 Display verification status (Yes / No)
    def verification_status(self, obj):
        return "Verified" if obj.user else "Not Verified"
    
    verification_status.short_description = "Verification"
    verification_status.admin_order_field = 'user'
