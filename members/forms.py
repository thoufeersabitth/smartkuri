from django import forms
from members.models import Member
from chitti.models import ChittiGroup
from subscriptions.utils import can_add_member

class MemberAddForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = Member
        fields = ['name', 'email', 'phone', 'address', 'aadhaar_no', 'assigned_chitti_group', 'password']

    def __init__(self, *args, admin_user=None, **kwargs):
        super().__init__(*args, **kwargs)

        # Add Bootstrap classes
        for field_name, field in self.fields.items():
            if field_name == 'assigned_chitti_group':
                field.widget.attrs.update({'class': 'form-select'})
            elif field_name == 'password':
                field.widget.attrs.update({'class': 'form-control'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

        if admin_user:
            # Only admin's groups
            groups = ChittiGroup.objects.filter(owner=admin_user)
            
            # Only groups that can still add members
            available_groups = [g for g in groups if can_add_member(g)]
            
            self.fields['assigned_chitti_group'].queryset = ChittiGroup.objects.filter(id__in=[g.id for g in available_groups])

            # Optional: show message if no groups available
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




        