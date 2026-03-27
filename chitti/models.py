import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
# ==================================================
# CHOICES
# ==================================================

COLLECTION_CHOICES = [
    (1, "1 Collection"),
    (2, "2 Collections"),
    (3, "3 Collections"),
    (4, "4 Collections"),
]

AUCTION_CHOICES = [
    (1, "1 Auction"),
    (2, "2 Auctions"),
    (3, "3 Auctions"),
    (4, "4 Auctions"),
]

AUCTION_TYPE_CHOICES = [
    ("monthly", "Monthly"),
    ("interval", "Interval"),
]


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
    collections_per_month = models.PositiveIntegerField(
        choices=COLLECTION_CHOICES,
        default=1
    )
    auction_type = models.CharField(
        max_length=10,
        choices=AUCTION_TYPE_CHOICES,
        default="monthly"
    )
    auctions_per_month = models.PositiveIntegerField(
        choices=AUCTION_CHOICES,
        default=1
    )
    auction_interval_months = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Only used when auction type is interval"
    )
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
    # SAVE
    # -----------------------------
    def save(self, *args, **kwargs):
        if self.monthly_amount and self.duration_months:
            self.total_amount = self.monthly_amount * self.duration_months
        if not self.code:
            self.code = f"CH-{uuid.uuid4().hex[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"

    # -----------------------------
    # VALIDATION
    # -----------------------------
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.auction_type == "interval":
            if not self.auction_interval_months:
                raise ValidationError("Interval months required")
            if self.auction_interval_months <= 0:
                raise ValidationError("Interval must be greater than 0")
            if self.auction_interval_months > self.duration_months:
                raise ValidationError("Interval cannot exceed duration")
        else:
            self.auction_interval_months = None

    # -----------------------------
    # PROPERTIES
    # -----------------------------
    @property
    def end_date(self):
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
    def total_auctions(self):
        if self.auction_type == "monthly":
            return self.duration_months * self.auctions_per_month
        if self.auction_type == "interval" and self.auction_interval_months:
            cycles = self.duration_months // self.auction_interval_months
            return cycles * self.auctions_per_month
        return 0

    @property
    def max_members(self):
        return self.total_auctions

    @property
    def total_members(self):
        return self.chitti_members.count()

    @property
    def monthly_collection(self):
        return self.total_members * self.monthly_amount

    @property
    def auction_share(self):
        if self.auctions_per_month:
            return self.monthly_collection / self.auctions_per_month
        return 0

    @property
    def collection_amount(self):
        return self.monthly_amount / self.collections_per_month

    # -----------------------------
    # AUCTION STRUCTURE ONLY
    # -----------------------------
    def generate_auctions(self):
        auctions = []
        if self.auction_type == "monthly":
            for month in range(1, self.duration_months + 1):
                for a in range(1, self.auctions_per_month + 1):
                    auctions.append((month, a))
        elif self.auction_type == "interval":
            for month in range(1, self.duration_months + 1):
                if (month - 1) % self.auction_interval_months == 0:
                    for a in range(1, self.auctions_per_month + 1):
                        auctions.append((month, a))
        return auctions

    # -----------------------------
    # CREATE AUCTIONS (DB SAVE)
    # -----------------------------
    def create_auctions(self, base_dates=None):
        from .models import Auction
        auctions = self.generate_auctions()
        for month, auction_no in auctions:
            if base_dates and auction_no <= len(base_dates):
                base_date = base_dates[auction_no - 1]
                auction_date = base_date + relativedelta(months=month - 1)
            else:
                auction_date = self.start_date + relativedelta(months=month - 1)
            Auction.objects.get_or_create(
                group=self,
                month_no=month,
                auction_no=auction_no,
                defaults={"auction_date": auction_date}
            )
# ==================================================
# Chitti Member
# ==================================================

class ChittiMember(models.Model):

    group = models.ForeignKey(
        ChittiGroup,
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
            return self.total_paid // self.group.monthly_amount
        return 0

    @property
    def next_due_date(self):
        if self.months_paid >= self.group.duration_months:
            return None

        return self.group.start_date + relativedelta(months=self.months_paid)

    @property
    def member_status(self):
        if self.pending_amount <= 0:
            return "Completed"
        return "Active"


# ==================================================
# Auction
# ==================================================

from django.db import models
from django.utils import timezone

class Auction(models.Model):

    group = models.ForeignKey(
        ChittiGroup,
        on_delete=models.CASCADE,
        related_name='auctions'
    )

    month_no = models.PositiveIntegerField()
    auction_no = models.PositiveIntegerField(default=1)

    auction_date = models.DateField()

    winner = models.ForeignKey(
        ChittiMember,
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
        unique_together = ('group', 'month_no', 'auction_no')
        ordering = ['month_no', 'auction_no']

    def __str__(self):
        return f"{self.group.name} - Month {self.month_no} Auction {self.auction_no}"

    # -----------------------------
    # STATUS
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
    # CORE LOGIC
    # -----------------------------
    def assign_winner(self, chitti_member, bid_amount=None):

        # 🔥 1️⃣ Already closed
        if self.is_closed:
            raise ValueError("Auction already closed!")

        # 🔥 2️⃣ Member validation
        if chitti_member.group != self.group:
            raise ValueError("Member not in this group!")

        # 🔥 3️⃣ Prevent duplicate winner
        already_won = Auction.objects.filter(
            group=self.group,
            winner=chitti_member
        ).exists()

        if already_won:
            raise ValueError("Member already won an auction!")

        # 🔥 4️⃣ Assign winner
        self.winner = chitti_member

        if bid_amount is not None:   # ✅ FIX
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

    collection_no = models.PositiveIntegerField()

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
        return f"{self.member.member.name} - ₹{self.amount}"