from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class StaffProfile(models.Model):
    ROLE_CHOICES = (
        ('group_admin', 'Group Admin'),
        ('admin', 'Admin'),
        ('collector', 'Cash Collector'),
        ('member', 'Member'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE)

    group = models.ForeignKey(
        'chitti.ChittiGroup',
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    phone = models.CharField(max_length=15)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

    is_blocked = models.BooleanField(default=False)
    is_subscribed = models.BooleanField(default=False)
    subscription_end = models.DateField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    # ✅ ADD THIS
    @property
    def is_active(self):
        return (
            self.is_subscribed and
            self.subscription_end and
            self.subscription_end >= timezone.now().date()
        )

    def subscription_status(self):
        if self.is_active:
            return "Active"
        return "Expired"

    def __str__(self):
        return f"{self.user.username} - {self.role}"
