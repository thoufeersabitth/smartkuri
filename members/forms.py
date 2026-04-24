from django import forms
from members.models import Member
from chitti.models import ChittiGroup
from subscriptions.utils import can_add_member

class MemberAddForm(forms.ModelForm):
    # Password field
    password = forms.CharField(widget=forms.PasswordInput(attrs={'placeholder': 'Enter password'}))
    
    # Email field - explicitly set as required
    email = forms.EmailField(
        required=True, 
        widget=forms.EmailInput(attrs={'placeholder': 'example@gmail.com'})
    )

    # Address field - TextArea for better UX
    address = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={
            'placeholder': 'Enter full address',
            'rows': 3
        })
    )

    class Meta:
        model = Member
        fields = ['name', 'email', 'phone', 'address', 'aadhaar_no', 'assigned_chitti_group', 'password']

    def __init__(self, *args, admin_user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # 1. FORCE Group field to be required
        self.fields['assigned_chitti_group'].required = True
        self.fields['assigned_chitti_group'].empty_label = "Select a Chitti Group"

        # 2. Add Bootstrap/Custom classes
        for field_name, field in self.fields.items():
            if field_name == 'assigned_chitti_group':
                field.widget.attrs.update({'class': 'form-select'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

        if admin_user:
            # Filter for admin's groups
            groups = ChittiGroup.objects.filter(owner=admin_user)
            
            # Filter groups that haven't reached the member limit
            available_groups = [g for g in groups if can_add_member(g)]
            
            # Update the queryset to only show groups the admin can actually add to
            self.fields['assigned_chitti_group'].queryset = ChittiGroup.objects.filter(
                id__in=[g.id for g in available_groups]
            )

            # If no groups are available, update the placeholder text
            if not available_groups:
                self.fields['assigned_chitti_group'].empty_label = "No groups available (limit reached)"


class MemberEditForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = [
            'name',
            'email',
            'phone',
            'address',
            'aadhaar_no',
            'assigned_chitti_group'
        ]




        