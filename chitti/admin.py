import random
from datetime import date
from django.contrib import admin
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import get_object_or_404, render
from .models import ChittiGroup, ChittiMember, Auction

@admin.register(ChittiGroup)
class ChittiGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_amount', 'duration_months', 'monthly_amount', 'start_date', 'view_spin_btn')
    
    # Fields marked as editable=False in the model MUST be in readonly_fields
    readonly_fields = ('total_amount', 'code')
    
    fields = (
        'name', 'phone', 'email', 'owner', 'parent_group', 
        'monthly_amount', 'duration_months', 'auction_type', 
        'auctions_per_month', 'auction_interval_months', 
        'start_date', 'collector', 'is_active', 'total_amount', 'code'
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('spin/<int:group_id>/', self.admin_site.admin_view(self.spin_view), name='chitti-spin'),
        ]
        return custom_urls + urls

    def view_spin_btn(self, obj):
        url = reverse('admin:chitti-spin', args=[obj.id])
        return format_html('<a class="button" style="background-color: #79aec8; color: white; padding: 5px 10px; border-radius: 4px;" href="{}">Spin Members</a>', url)
    
    view_spin_btn.short_description = 'Auction Action'

    def spin_view(self, request, group_id):
        group = get_object_or_404(ChittiGroup, id=group_id)
        
        # Get members who haven't won yet
        past_winners_ids = Auction.objects.filter(
            group=group, 
            winner__isnull=False
        ).values_list('winner_id', flat=True)
        
        eligible_members = ChittiMember.objects.filter(group=group).exclude(id__in=past_winners_ids)
        
        winner = None

        if request.method == "POST" and eligible_members.exists():
            winner = random.choice(eligible_members)

            # Find the first empty pre-generated Auction slot
            current_slot = Auction.objects.filter(
                group=group, 
                winner__isnull=True
            ).order_by('month_no', 'auction_no').first()

            if current_slot:
                current_slot.winner = winner
                current_slot.auction_date = date.today()
                current_slot.save()
            else:
                Auction.objects.create(
                    group=group,
                    month_no=group.current_month,
                    auction_date=date.today(),
                    winner=winner,
                    bid_amount=0
                )

        return render(request, "admin/chitti_spin.html", {
            "group": group,
            "members": eligible_members,
            "winner": winner,
        })

@admin.register(ChittiMember)
class ChittiMemberAdmin(admin.ModelAdmin):
    # REMOVED 'is_active' to fix admin.E108 and admin.E116 errors
    list_display = ('member', 'group', 'token_no')
    list_filter = ('group',)

@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ('group', 'month_no', 'auction_no', 'winner', 'auction_date', 'bid_amount')
    list_filter = ('group', 'month_no')
    readonly_fields = ('month_no', 'auction_no')