from django import forms
from subscriptions.models import SubscriptionPlan
from django.contrib.auth.models import User 
from chitti.models import ChittiGroup




class GroupSignUpForm(forms.Form):

    group_name = forms.CharField(
        label="Chitti Group Name",
        widget=forms.TextInput(attrs={
            'placeholder': 'Group Name',
            'class': 'form-control'
        })
    )

    phone = forms.CharField(
        label="Admin Phone",
        widget=forms.TextInput(attrs={
            'placeholder': 'Phone Number',
            'class': 'form-control'
        })
    )

    email = forms.EmailField(
        label="Admin Email",
        widget=forms.EmailInput(attrs={
            'placeholder': 'Admin Email',
            'class': 'form-control'
        })
    )

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Password',
            'class': 'form-control'
        })
    )

    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            'placeholder': 'Confirm Password',
            'class': 'form-control'
        })
    )

    description = forms.CharField(
        label="Group Description",
        widget=forms.Textarea(attrs={
            'placeholder': 'Enter description',
            'rows': 3,
            'class': 'form-control'
        }),
        required=False
    )

    # 🔥 IMPORTANT FIX — MUST MATCH HIDDEN INPUT
    plan = forms.ModelChoiceField(
        queryset=SubscriptionPlan.objects.filter(is_active=True),
        widget=forms.HiddenInput(),   # ✅ NOT Select
        required=True
    )

    def clean(self):
        cleaned_data = super().clean()

        password1 = cleaned_data.get('password1')
        password2 = cleaned_data.get('password2')

        if password1 and password2 and password1 != password2:
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
