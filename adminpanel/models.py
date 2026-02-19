from django.db import models
from accounts.models import StaffProfile

# System Notifications
class SystemNotification(models.Model):
    message = models.TextField()
    target_admin = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
