# payments/admin.py

from django.contrib import admin
from .models import Payment

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'collected_by',
        'group',
        'amount',
        'payment_method',
        'payment_status',
        'paid_date',
        'subscription_plan',
        'subscription_start',
        'subscription_end',
    )

    list_filter = (
        'payment_method',
        'payment_status',
        'subscription_plan',
        'paid_date',
    )

    search_fields = (
        'transaction_id',
        'invoice_number',
        'group__name',
        'collected_by__user__username',
    )

    readonly_fields = (
        'transaction_id',
        'invoice_number',
        'created_at',
        'updated_at',
    )
