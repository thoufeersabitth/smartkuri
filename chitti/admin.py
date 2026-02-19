from django.contrib import admin
from django.urls import path
from django.shortcuts import render, get_object_or_404
from django.utils.html import format_html
from .models import ChittiGroup, ChittiMember, Auction
import random
from datetime import date

@admin.register(ChittiGroup)
class ChittiGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_amount', 'duration_months', 'monthly_amount', 'start_date', 'view_spin')
    
    # Add custom admin URL for spin
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('spin/<int:group_id>/', self.admin_site.admin_view(self.spin_view), name='chitti-spin'),
        ]
        return custom_urls + urls

    # Button to go to spin page
    def view_spin(self, obj):
        return format_html('<a class="button" href="spin/{}/">Spin Members</a>', obj.id)
    view_spin.short_description = 'Spin Members'
    view_spin.allow_tags = True

    # Spin view
    def spin_view(self, request, group_id):
        group = get_object_or_404(ChittiGroup, id=group_id)
        members = ChittiMember.objects.filter(group=group)
        winner = None

        if request.method == "POST" and members.exists():
            winner_member = random.choice(members)
            winner = winner_member.member

            # Save to Auction model
            Auction.objects.create(
                group=group,
                month_no=(group.duration_months - len(members) + 1),
                auction_date=date.today(),
                winner=winner,
                bid_amount=0
            )

        return render(request, "admin/chitti_spin.html", {
            "group": group,
            "members": members,
            "winner": winner,
        })

# Register other models normally
@admin.register(ChittiMember)
class ChittiMemberAdmin(admin.ModelAdmin):
    list_display = ('member', 'group', 'token_no')

@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ('group', 'month_no', 'winner', 'bid_amount', 'auction_date')
