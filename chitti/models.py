from builtins import property
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta

# ==================================================
# Chitti Group
# ==================================================
class ChittiGroup(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True, editable=False)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_chitti_groups'
    )

    parent_group = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='sub_groups'
    )

    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    monthly_amount = models.DecimalField(max_digits=12, decimal_places=2)
    duration_months = models.PositiveIntegerField()
    start_date = models.DateField()

    collector = models.ForeignKey(
        'accounts.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={'role': 'collector'},
        related_name='assigned_chitti_groups'
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # -----------------------------
    # ✅ Corrected Save Method
    # -----------------------------
    def save(self, *args, **kwargs):
        # Auto calculate total_amount whenever monthly_amount or duration changes
        if self.monthly_amount and self.duration_months:
            self.total_amount = self.monthly_amount * self.duration_months

        # Generate unique code if not exists
        if not self.code:
            self.code = f"CH-{uuid.uuid4().hex[:6].upper()}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

    # -----------------------------
    # Properties
    # -----------------------------
    @property
    def end_date(self):
        # Inclusive end date
        return self.start_date + relativedelta(months=self.duration_months) - relativedelta(days=1)

    @property
    def current_month(self):
        today = timezone.now().date()
        if today < self.start_date:
            return 0
        months = (today.year - self.start_date.year) * 12 + (today.month - self.start_date.month) + 1
        return min(months, self.duration_months)

    @property
    def group_status(self):
        today = timezone.now().date()
        if not self.is_active:
            return "Completed"
        if today < self.start_date:
            return "Upcoming"
        if self.start_date <= today <= self.end_date:
            return "Running"
        return "Completed"

    @property
    def total_members(self):
        return self.chitti_members.count()



from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta

# ==================================================
# Chitti Member
# ==================================================
class ChittiMember(models.Model):
    group = models.ForeignKey(
        'chitti.ChittiGroup',
        on_delete=models.CASCADE,
        related_name='chitti_members'
    )
    member = models.ForeignKey(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='chitti_memberships'
    )
    token_no = models.PositiveIntegerField()
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group', 'token_no')
        ordering = ['token_no']

    def __str__(self):
        return f"{self.member.name} (Token {self.token_no})"

    # -----------------------------
    # PAYMENT STATUS
    # -----------------------------
    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments.all())

    @property
    def expected_amount(self):
        return self.group.monthly_amount * self.group.duration_months

    @property
    def pending_amount(self):
        return max(0, self.expected_amount - self.total_paid)

    @property
    def months_paid(self):
        if self.group.monthly_amount > 0:
            return int(self.total_paid / self.group.monthly_amount)
        return 0

    @property
    def next_due_date(self):
        if self.months_paid >= self.group.duration_months:
            return None
        return self.group.start_date + relativedelta(months=self.months_paid)

    # -----------------------------
    # MEMBER STATUS (SPIN PURPOSE)
    # -----------------------------
    @property
    def member_status(self):
        """
        Spin-il check cheyyan vendi simplified:
        - Completed → fully paid
        - Active → all other members (even if overdue)
        """
        if self.pending_amount <= 0:
            return "Completed"
        return "Active"


# ==================================================
# Auction
# ==================================================
class Auction(models.Model):
    group = models.ForeignKey(
        'chitti.ChittiGroup',
        on_delete=models.CASCADE,
        related_name='auctions'
    )
    month_no = models.PositiveIntegerField()
    auction_date = models.DateField()

    # ✅ Winner is ChittiMember
    winner = models.ForeignKey(
        'chitti.ChittiMember',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='won_auctions'
    )
    bid_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group', 'month_no')
        ordering = ['month_no']

    def __str__(self):
        return f"{self.group.name} - Month {self.month_no}"

    # -----------------------------
    # STATUS HELPERS
    # -----------------------------
    @property
    def is_closed(self):
        return self.winner is not None

    @property
    def is_upcoming(self):
        return self.auction_date > timezone.now().date()

    @property
    def is_today(self):
        return self.auction_date == timezone.now().date()

    # -----------------------------
    # ASSIGN WINNER (SAFE)
    # -----------------------------
    def assign_winner(self, chitti_member, bid_amount=None):
        if self.is_closed:
            raise ValueError("Auction already closed!")
        if chitti_member.group != self.group:
            raise ValueError("Member does not belong to this group!")
        if chitti_member.member_status not in ["Active", "Completed"]:
            raise ValueError("Only eligible members can win!")

        self.winner = chitti_member
        if bid_amount is not None:
            self.bid_amount = bid_amount
        self.save()

# ==================================================
# Member Payment
# ==================================================
class MemberPayment(models.Model):
    member = models.ForeignKey(
        ChittiMember,
        on_delete=models.CASCADE,
        related_name='payments'
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_date = models.DateField(auto_now_add=True)

    collector = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collected_payments'
    )

    class Meta:
        ordering = ['paid_date']

    def __str__(self):
        return f"{self.member.member.name} - ₹{self.amount} on {self.paid_date}"
