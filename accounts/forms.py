from django import forms
from subscriptions.models import SubscriptionPlan
from django.contrib.auth.models import User 
from chitti.models import ChittiGroup


class GroupSignUpForm(forms.Form):
    group_name = forms.CharField(widget=forms.TextInput(attrs={'placeholder':'Group Name','class':'form-control'}))
    phone = forms.CharField(widget=forms.TextInput(attrs={'placeholder':'Phone Number','class':'form-control'}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={'placeholder':'Admin Email','class':'form-control'}))
    password1 = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder':'Password','class':'form-control'}))
    password2 = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder':'Confirm Password','class':'form-control'}))
    description = forms.CharField(widget=forms.Textarea(attrs={'placeholder':'Enter description','rows':3,'class':'form-control'}), required=False)

    # ✅ Group details
    monthly_amount = forms.DecimalField(widget=forms.NumberInput(attrs={'class':'form-control'}))
    duration_months = forms.IntegerField(widget=forms.NumberInput(attrs={'class':'form-control'}))
    collections_per_month = forms.ChoiceField(
        choices=ChittiGroup._meta.get_field('collections_per_month').choices,
        widget=forms.Select(attrs={'class':'form-control'})
    )
    auction_type = forms.ChoiceField(
        choices=ChittiGroup._meta.get_field('auction_type').choices,
        widget=forms.Select(attrs={'class':'form-control'})
    )
    auctions_per_month = forms.ChoiceField(
        choices=ChittiGroup._meta.get_field('auctions_per_month').choices,
        widget=forms.Select(attrs={'class':'form-control'})
    )
    auction_interval_months = forms.IntegerField(required=False, widget=forms.NumberInput(attrs={'class':'form-control'}))
    start_date = forms.DateField(widget=forms.DateInput(attrs={'type':'date','class':'form-control'}))
    auction_dates = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder':'dd-mm-yyyy, dd-mm-yyyy', 'class':'form-control'}))

    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        widget=forms.HiddenInput(),
        required=True
    )

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('password1') != cleaned_data.get('password2'):
            raise forms.ValidationError("Passwords do not match")
        return cleaned_data


class CashCollectorCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label="Username")
    email = forms.EmailField(max_length=254, label="Email")
    phone = forms.CharField(max_length=15, label="Phone")
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")

    group = forms.ModelChoiceField(
        queryset=ChittiGroup.objects.none(),  # start empty
        label="Assign to Group",
        empty_label="Select Group"
    )

    def __init__(self, *args, **kwargs):
        admin_user = kwargs.pop('admin_user', None)  # logged-in Group Admin
        super().__init__(*args, **kwargs)
        if admin_user:
            # 🔹 Use 'owner' field instead of 'admin'
            self.fields['group'].queryset = ChittiGroup.objects.filter(owner=admin_user)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        # Password match
        if password and confirm_password and password != confirm_password:
            raise forms.ValidationError("Passwords do not match")

        # Username uniqueness
        if username and User.objects.filter(username=username).exists():
            raise forms.ValidationError("Username is already taken")

        # Email uniqueness
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError("Email is already registered")

        return cleaned_data
    

class CashCollectorEditForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        label="Username",
        required=False,   # ✅ IMPORTANT
        widget=forms.TextInput(attrs={
            'readonly': 'readonly',
            'class': 'form-control'
        })
    )

    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )

    phone = forms.CharField(
        max_length=15,
        label="Phone",
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    group = forms.ModelChoiceField(
        queryset=ChittiGroup.objects.none(),
        label="Assign to Group",
        empty_label="Select Group",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        admin_user = kwargs.pop('admin_user', None)
        super().__init__(*args, **kwargs)
        if admin_user:
            self.fields['group'].queryset = ChittiGroup.objects.filter(owner=admin_user)
