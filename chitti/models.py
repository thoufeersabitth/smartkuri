from calendar import monthrange
from datetime import datetime
from decimal import Decimal
import random
import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from datetime import date
# ==================================================
# CHOICES
# ==================================================

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



class ChittiGroup(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)

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

    total_amount = models.DecimalField(max_digits=12, decimal_places=2, editable=False)
    monthly_amount = models.DecimalField(max_digits=12, decimal_places=2)
    duration_months = models.PositiveIntegerField()

    registration_start_date = models.DateField(null=True, blank=True)

    auction_type = models.CharField(max_length=10, default="monthly")
    auctions_per_month = models.PositiveIntegerField(default=1)
    auction_interval_months = models.PositiveIntegerField(null=True, blank=True)

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
    # SAVE (FIXED)
    # -----------------------------
    def save(self, *args, **kwargs):
        if self.monthly_amount and self.duration_months:
            self.total_amount = Decimal(str(self.monthly_amount)) * int(self.duration_months)

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
                raise ValidationError("Interval must be > 0")
            if self.auction_interval_months > self.duration_months:
                raise ValidationError("Interval > duration not allowed")
        else:
            self.auction_interval_months = None

    # -----------------------------
    # PROPERTIES
    # -----------------------------
    @property
    def end_date(self):
        return self.start_date + relativedelta(months=self.duration_months) - relativedelta(days=1)

    # ✅ NEW PROPERTY ADDED
    @property
    def current_month(self):
        if not self.start_date:
            return 1

        today = date.today()
        diff = (today.year - self.start_date.year) * 12 + (today.month - self.start_date.month)

        current = diff + 1

        # limit between 1 and duration
        return max(1, min(current, self.duration_months))

    @property
    def total_members(self):
        return self.chitti_members.count()

    @property
    def monthly_collection_target(self):
        return Decimal(self.total_members) * Decimal(self.monthly_amount)

    @property
    def auction_share_value(self):
        if self.auctions_per_month:
            return self.monthly_collection_target / self.auctions_per_month
        return 0

    from calendar import monthrange



    # -----------------------------
    # AUCTION STRUCTURE
    # -----------------------------
    def generate_auctions_structure(self):
        auctions = []

        if self.auction_type == "monthly":
            for m in range(1, self.duration_months + 1):
                for a in range(1, self.auctions_per_month + 1):
                    auctions.append((m, a))

        elif self.auction_type == "interval" and self.auction_interval_months:
            for m in range(1, self.duration_months + 1):
                if (m - 1) % self.auction_interval_months == 0:
                    for a in range(1, self.auctions_per_month + 1):
                        auctions.append((m, a))

        return auctions

    # -----------------------------
    # CREATE AUCTIONS (FINAL FIX)
    # -----------------------------
    from calendar import monthrange


    def create_auctions(self, base_dates=None):
        from .models import Auction

        # 🧹 clear old auctions
        Auction.objects.filter(group=self).delete()

        # =========================
        # 🟢 MANUAL MODE
        # =========================
        if base_dates:
            for i, d in enumerate(base_dates, start=1):
                Auction.objects.create(
                    group=self,
                    month_no=i,
                    auction_no=i,
                    auction_date=d
                )
            return

        # =========================
        # 🔵 AUTO MODE (FIXED)
        # =========================
        start = self.start_date
        base_day = start.day

        for month_no in range(1, self.duration_months + 1):

            temp_date = start + relativedelta(months=month_no - 1)

            year = temp_date.year
            month = temp_date.month

            last_day = monthrange(year, month)[1]
            safe_day = min(base_day, last_day)

            auction_date = date(year, month, safe_day)

            Auction.objects.create(
                group=self,
                month_no=month_no,
                auction_no=1,   # (or remove if not needed per month logic)
                auction_date=auction_date
        )
    # -----------------------------
    # CREATE AUCTIONS (FIXED)
    # -----------------------------
    
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



class Auction(models.Model):

    SELECTION_CHOICES = (
        ('auto', 'Auto'),
        ('manual', 'Manual'),
    )

    group = models.ForeignKey(
        'ChittiGroup',
        on_delete=models.CASCADE,
        related_name='auctions'
    )

    month_no = models.PositiveIntegerField()
    auction_no = models.PositiveIntegerField(default=1)

    auction_date = models.DateField()

    # 🔥 NEW FIELD
    selection_type = models.CharField(
        max_length=10,
        choices=SELECTION_CHOICES,
        default='auto'
    )

    winner = models.ForeignKey(
        'ChittiMember',
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
        """
        Manual winner assignment
        """

        # 🔥 1️⃣ Already closed check
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

        if bid_amount is not None:
            self.bid_amount = bid_amount

        self.save()

    # -----------------------------
    # AUTO WINNER (SPIN)
    # -----------------------------
    def auto_select_winner(self):

        if self.is_closed:
            raise ValueError("Auction already closed!")

        # 🔥 FIXED HERE
        members = self.group.chitti_members.all()

        previous_winners = Auction.objects.filter(
            group=self.group,
            winner__isnull=False
        ).values_list('winner_id', flat=True)

        eligible_members = members.exclude(id__in=previous_winners)

        if not eligible_members.exists():
            raise ValueError("No eligible members left!")

        winner = random.choice(list(eligible_members))

        self.assign_winner(winner)

        return winner

    # -----------------------------
    # MAIN ENTRY METHOD (🔥 BEST)
    # -----------------------------
    def run_auction(self, member=None, bid_amount=None):
        """
        Single method to handle both auto + manual
        """

        if self.selection_type == 'auto':
            return self.auto_select_winner()

        elif self.selection_type == 'manual':
            if not member:
                raise ValueError("Manual mode requires a selected member!")

            self.assign_winner(member, bid_amount)
            return member

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