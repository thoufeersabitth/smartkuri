from django.db import models, transaction
from django.utils import timezone
from accounts.models import StaffProfile
from chitti.models import ChittiGroup
from members.models import Member
import uuid, random
from datetime import datetime


# ----------------------------
# INSTALLMENT MODEL
# ----------------------------
from django.db import models, transaction
from django.utils import timezone
from accounts.models import StaffProfile
from chitti.models import ChittiGroup
from members.models import Member
import uuid, random
from datetime import datetime


class Installment(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='installments')
    group = models.ForeignKey(ChittiGroup, on_delete=models.CASCADE)
    month = models.DateField()
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    class Meta:
        ordering = ['month']

    def __str__(self):
        return f"{self.member.name} - {self.month.strftime('%B %Y')} - {self.status}"


# ----------------------------
# PAYMENT MODEL
# ----------------------------
class Payment(models.Model):
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name='collections', null=True)
    group = models.ForeignKey(ChittiGroup, on_delete=models.CASCADE, null=True)

    collected_by = models.ForeignKey(StaffProfile, on_delete=models.CASCADE)
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

    paid_date = models.DateField(default=timezone.now)
    paid_time = models.TimeField(auto_now_add=True)

    transaction_id = models.CharField(max_length=100, unique=True, blank=True)
    invoice_number = models.CharField(max_length=100, unique=True, blank=True)

    # collector → admin flow
    sent_to_admin = models.BooleanField(default=False)

    # old compatibility
    received_by_admin = models.BooleanField(default=False)

    ADMIN_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    admin_status = models.CharField(
        max_length=10,
        choices=ADMIN_STATUS_CHOICES,
        default='pending'
    )

     # 🔔 NEW FIELD (IMPORTANT)
    is_seen = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    # ----------------------------
    # SAVE (NO AUTO ALLOCATION HERE ❌)
    # ----------------------------
    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if not self.transaction_id:
            self.transaction_id = uuid.uuid4().hex[:12].upper()

        if not self.invoice_number:
            self.invoice_number = f"INV{datetime.now().strftime('%Y%m%d')}{random.randint(1000,9999)}"

        # sync
        self.received_by_admin = (self.admin_status == 'approved')

        super().save(*args, **kwargs)

        # ❌ IMPORTANT: DO NOT allocate here anymore


    # ----------------------------
    # ALLOCATION (ONLY APPROVE TIME)
    # ----------------------------
    def allocate_payment(self):
        remaining = self.amount

        installments = Installment.objects.filter(
            member=self.member,
            group=self.group,
            status__in=['pending', 'partial']
        ).order_by('month')

        with transaction.atomic():
            for inst in installments:
                if remaining <= 0:
                    break

                due = inst.amount_due - inst.amount_paid
                if due <= 0:
                    continue

                pay_amount = min(remaining, due)

                inst.amount_paid += pay_amount
                inst.status = 'paid' if inst.amount_paid >= inst.amount_due else 'partial'
                inst.save()

                PaymentAllocation.objects.create(
                    payment=self,
                    installment=inst,
                    amount=pay_amount
                )

                remaining -= pay_amount


    # ----------------------------
    # REVERSE (ON REJECT)
    # ----------------------------
    def reverse_allocation(self):
        allocations = self.allocations.all()

        with transaction.atomic():
            for alloc in allocations:
                inst = alloc.installment

                inst.amount_paid -= alloc.amount

                if inst.amount_paid <= 0:
                    inst.amount_paid = 0
                    inst.status = 'pending'
                elif inst.amount_paid < inst.amount_due:
                    inst.status = 'partial'

                inst.save()

            allocations.delete()


    def __str__(self):
        return f"{self.member.name if self.member else 'No Member'} - ₹{self.amount}"


# ----------------------------
# PAYMENT ALLOCATION MODEL
# ----------------------------
class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    installment = models.ForeignKey(Installment, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.amount} → {self.installment}"