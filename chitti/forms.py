# chitti/forms.py
from django import forms
from .models import ChittiGroup, ChittiMember, Auction
from dateutil.relativedelta import relativedelta


class ChittiGroupForm(forms.ModelForm):
    class Meta:
        model = ChittiGroup
        # FIX: Removed 'total_amount' because it's non-editable.
        # It will still calculate automatically in your Model's save() method.
        fields = [
            'name', 
            'duration_months', 
            'monthly_amount', 
            'start_date', 
            'auction_type', 
            'auctions_per_month'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Group Name'}),
            'monthly_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'duration_months': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class ChittiMemberForm(forms.ModelForm):
    class Meta:
        model = ChittiMember
        fields = ['group', 'member', 'token_no']


class AuctionForm(forms.ModelForm):

    class Meta:
        model = Auction
        fields = ["group", "auction_date"]
        widgets = {
            "auction_date": forms.DateInput(attrs={"type": "date"})
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

        # Show only logged-in user's groups
        if user:
            self.fields["group"].queryset = ChittiGroup.objects.filter(owner=user)

    def clean(self):
        cleaned_data = super().clean()
        group = cleaned_data.get("group")
        auction_date = cleaned_data.get("auction_date")

        if not group or not auction_date:
            return cleaned_data

        # 🔹 1️⃣ Date inside group duration
        group_end_date = group.start_date + relativedelta(
            months=group.duration_months
        )

        if auction_date < group.start_date or auction_date >= group_end_date:
            raise forms.ValidationError(
                "Auction date exceeds group duration period."
            )

        # 🔹 2️⃣ Same month duplicate
        month_exists = group.auctions.filter(
            auction_date__year=auction_date.year,
            auction_date__month=auction_date.month
        ).exists()

        if month_exists:
            raise forms.ValidationError(
                "An auction already exists for this month."
            )

        # 🔹 3️⃣ Duration limit
        if group.auctions.count() >= group.duration_months:
            raise forms.ValidationError(
                "Auction limit reached for this group."
            )

        return cleaned_data