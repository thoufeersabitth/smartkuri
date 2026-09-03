from django import forms
from subscriptions.models import SubscriptionPlan
from django.contrib.auth.models import User 
from chitti.models import AUCTION_CHOICES, AUCTION_TYPE_CHOICES,  ChittiGroup


# forms.py

from django import forms

class GroupSignUpForm(forms.Form):
    # Added Name field here
    name = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'Full Name', 
            'class': 'form-control'
        }),
        max_length=100,
        required=True
    )
    
    phone = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'Phone Number', 
            'class': 'form-control'
        })
    )
    
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'placeholder': 'Admin Email', 
            'class': 'form-control'
        })
    )
    
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Password', 
            'class': 'form-control'
        })
    )
    
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Confirm Password', 
            'class': 'form-control'
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        # Check if passwords match
        if password1 and password2 and password1 != password2:
            raise forms.ValidationError("Passwords do not match")
            
        return cleaned_data
        
class CashCollectorCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label="Username")
    email = forms.EmailField(max_length=254, label="Email")
    phone = forms.CharField(max_length=15, label="Phone")
    password = forms.CharField(widget=forms.PasswordInput, label="Password", required=False)
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm Password", required=False)
    existing_user_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    group = forms.ModelChoiceField(
        queryset=ChittiGroup.objects.none(),
        label="Assign to Group",
        empty_label="Select Group"
    )

    def __init__(self, *args, **kwargs):
        admin_user = kwargs.pop('admin_user', None)
        super().__init__(*args, **kwargs)
        if admin_user:
            self.fields['group'].queryset = ChittiGroup.objects.filter(owner=admin_user)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        existing_user_id = cleaned_data.get("existing_user_id")

        if existing_user_id:
            # Skip password validation & unique checks for existing user
            return cleaned_data

        # Standard new user validation
        if not password:
            self.add_error('password', 'Password is required for new collector.')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'Passwords do not match.')

        if username and User.objects.filter(username=username).exists():
            self.add_error('username', 'Username is already taken.')

        if email and User.objects.filter(email=email).exists():
            self.add_error('email', 'Email is already registered.')

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
