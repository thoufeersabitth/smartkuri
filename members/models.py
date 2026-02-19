from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta


class Member(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_LEFT = 'left'
    STATUS_DEFAULTED = 'defaulted'
    STATUS_COMPLETED = 'completed'

    STATUS_CHOICES = (
        (STATUS_ACTIVE, 'Active'),
        (STATUS_LEFT, 'Left'),
        (STATUS_DEFAULTED, 'Defaulted'),
        (STATUS_COMPLETED, 'Completed'),
    )

    # 🔗 Login related
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='member_profile'
    )

    # 👤 Basic Details
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=15, unique=True)
    address = models.TextField(blank=True)
    aadhaar_no = models.CharField(max_length=20, blank=True, null=True)

    # 📅 Joining
    join_date = models.DateField(auto_now_add=True)

    # 👥 Chitti Group
    assigned_chitti_group = models.ForeignKey(
        'chitti.ChittiGroup',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='members'
    )

    # 💰 Financial Details
    monthly_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    total_paid = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE
    )

    # 🔐 OTP
    email_otp = models.CharField(max_length=6, blank=True, null=True)
    otp_created_at = models.DateTimeField(blank=True, null=True)

    is_first_login = models.BooleanField(default=True)

    # -----------------------------
    # Pending amount
    # -----------------------------
    @property
    def pending_amount(self):
        return max(self.monthly_amount - self.total_paid, 0)

    # -----------------------------
    # OTP expiry
    # -----------------------------
    def is_otp_expired(self):
        if not self.otp_created_at:
            return True
        return timezone.now() > self.otp_created_at + timedelta(minutes=5)

    # -----------------------------
    # Computed member status
    # -----------------------------
    @property
    def member_status(self):
        """Return Active / Completed / Defaulted / Left"""
        # If manually marked left
        if self.status == self.STATUS_LEFT:
            return "Left"

        # Fully paid
        if self.total_paid >= self.monthly_amount:
            return "Completed"

        # Payment overdue
        if self.assigned_chitti_group:
            # Calculate expected paid months
            today = timezone.now().date()
            months_elapsed = (today.year - self.assigned_chitti_group.start_date.year) * 12 + \
                             (today.month - self.assigned_chitti_group.start_date.month) + 1
            expected_amount = self.assigned_chitti_group.monthly_amount * months_elapsed

            if self.total_paid < expected_amount:
                return "Defaulted"

        # Otherwise active
        return "Active"

    def __str__(self):
        return f"{self.name} ({self.phone})"

    class Meta:
        verbose_name = "Member"
        verbose_name_plural = "Members"
        ordering = ['name']
