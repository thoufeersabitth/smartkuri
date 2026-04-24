from django.contrib import admin
from .models import Payment, Installment, PaymentAllocation

# This allows you to see the allocation details directly inside the Payment view
class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    readonly_fields = ('installment', 'amount')
    can_delete = False

# ✅ INSTALLMENT ADMIN
@admin.register(Installment)
class InstallmentAdmin(admin.ModelAdmin):
    list_display = ('member', 'group', 'month', 'amount_due', 'amount_paid', 'status')
    list_filter = ('group', 'status', 'month')
    search_fields = ('member__name', 'group__group_name') # Fixed group field name if necessary
    readonly_fields = ('amount_paid', 'status')

# ✅ PAYMENT ALLOCATION ADMIN
@admin.register(PaymentAllocation)
class PaymentAllocationAdmin(admin.ModelAdmin):
    list_display = ('payment', 'installment', 'amount')
    list_filter = ('installment__group',)
    search_fields = ('payment__transaction_id', 'installment__member__name')
    readonly_fields = ('payment', 'installment', 'amount')

# ✅ PAYMENT ADMIN
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    # Removed the subscription fields from list_display
    list_display = (
        'invoice_number', # Better to show invoice than ID
        'member',
        'collected_by',
        'group',
        'amount',
        'payment_method',
        'payment_status',
        'paid_date',
    )

    # Removed the subscription_plan from list_filter
    list_filter = (
        'payment_method',
        'payment_status',
        'paid_date',
        'group',
    )

    search_fields = (
        'transaction_id',
        'invoice_number',
        'group__group_name',
        'collected_by__user__username',
        'member__name',
    )

    readonly_fields = (
        'transaction_id',
        'invoice_number',
        'created_at',
        'updated_at',
    )
    
    # Adding the inline helps you track which months the money went to
    inlines = [PaymentAllocationInline]