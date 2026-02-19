from django.db import models
from django.utils import timezone
from datetime import timedelta, datetime, MAXYEAR
from chitti.models import ChittiGroup


class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=50)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_days = models.PositiveIntegerField()
    max_members = models.PositiveIntegerField()
    max_groups = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class GroupSubscription(models.Model):
    group = models.OneToOneField(
        ChittiGroup,
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.PROTECT
    )
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        # Subscription ONLY allowed for MAIN group
        if self.group.parent_group is not None:
            raise ValueError(
                "Subscription is allowed only for main group"
            )
        super().save(*args, **kwargs)

    def activate(self, start_date=None):
        start = start_date or timezone.now()
        self.start_date = start

        try:
            self.end_date = start + timedelta(
                days=self.plan.duration_days,
                hours=23,
                minutes=59,
                seconds=59
            )

            if self.end_date.year > MAXYEAR:
                self.end_date = datetime(
                    MAXYEAR, 12, 31, 23, 59, 59,
                    tzinfo=timezone.utc
                )

        except OverflowError:
            self.end_date = datetime(
                MAXYEAR, 12, 31, 23, 59, 59,
                tzinfo=timezone.utc
            )

        self.is_active = True
        self.save(update_fields=['start_date', 'end_date', 'is_active'])

    def has_expired(self):
        if not self.end_date:
            return False
        if self.end_date.year >= MAXYEAR:
            return False
        return timezone.now() > self.end_date

    def is_current(self):
        if not self.end_date:
            return True
        if self.end_date.year >= MAXYEAR:
            return True
        return timezone.now() <= self.end_date

    def __str__(self):
        return f"{self.group.name} - {self.plan.name}"
