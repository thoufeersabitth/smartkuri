from builtins import getattr, max, min, property, sum, super
from django.db import models
from django.utils import timezone
from accounts.models import StaffProfile
from chitti.models import ChittiGroup
from subscriptions.models import SubscriptionPlan
from members.models import Member
from datetime import timedelta, datetime
import uuid, random


# -----------------------------
# Payment Model –
# -----------------------------
class Payment(models.Model):
    member = models.ForeignKey(
        Member,
        on_delete=models.CASCADE,
        related_name='collections',
        null=True,
        blank=True
    )

    collected_by = models.ForeignKey(
        StaffProfile,
        on_delete=models.CASCADE
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    PAYMENT_METHODS = [
        ('razorpay', 'Razorpay'),
        ('cash', 'Cash'),
        ('upi', 'UPI'),
        ('bank', 'Bank Transfer')
    ]
    payment_method = models.CharField(max_length=30, choices=PAYMENT_METHODS, default='cash')

    PAYMENT_STATUS = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('pending', 'Pending')
    ]
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='success')

    group = models.ForeignKey(ChittiGroup, on_delete=models.SET_NULL, null=True, blank=True)
    subscription_plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True)

    subscription_start = models.DateField(null=True, blank=True)
    subscription_end = models.DateField(null=True, blank=True)

    paid_date = models.DateField(default=timezone.now)
    paid_time = models.TimeField(auto_now_add=True)

    transaction_id = models.CharField(max_length=50, unique=True, blank=True)
    invoice_number = models.CharField(max_length=50, unique=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -----------------------------
    # Save method for transaction, invoice & subscription
    # -----------------------------
    def save(self, *args, **kwargs):
        creating = self.pk is None

        if not self.transaction_id:
            self.transaction_id = uuid.uuid4().hex[:12].upper()
        if not self.invoice_number:
            now = datetime.now()
            self.invoice_number = f"INV{now.strftime('%Y%m%d')}{random.randint(1000,9999)}"

        super().save(*args, **kwargs)

        if creating and self.payment_status == 'success' and self.subscription_plan and self.group:
            start_date = timezone.now().date()
            end_date = start_date + timedelta(days=self.subscription_plan.duration_days)
            Payment.objects.filter(pk=self.pk).update(
                subscription_start=start_date,
                subscription_end=end_date
            )

    # -----------------------------
    # Pending amount – auto from member total_paid
    # -----------------------------
    @property
    def pending_amount(self):
        if self.member:
            total_paid = sum(p.amount for p in self.member.collections.filter(payment_status='success'))
            return max(self.member.monthly_amount - total_paid, 0)
        return 0


    # -----------------------------
    # Subscription active check
    # -----------------------------
    def is_subscription_active(self):
        return self.subscription_end and self.subscription_end >= timezone.now().date()

    def __str__(self):
        member_name = self.member.name if self.member else "No Member"
        return f"{member_name} - ₹{self.amount} ({self.payment_status})"
