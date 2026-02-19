from django import forms
from payments.models import Payment
from chitti.models import ChittiGroup, ChittiMember


class PaymentForm(forms.ModelForm):
    group = forms.ModelChoiceField(
        queryset=ChittiGroup.objects.none(),
        label="Chitti Group",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    chitti_member = forms.ModelChoiceField(
        queryset=ChittiMember.objects.none(),
        label="Member",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    class Meta:
        model = Payment
        fields = [
            'group',
            'chitti_member',
            'amount',
            'paid_date',
            'payment_method',
            'payment_status',
        ]
        widgets = {
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'paid_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'payment_status': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        initial_group = kwargs.pop('initial_group', None)
        super().__init__(*args, **kwargs)

        # Load only groups owned by the admin
        if user:
            self.fields['group'].queryset = ChittiGroup.objects.filter(owner=user)

        # Determine selected group (POST, GET param, or initial)
        group_id = self.data.get('group') or initial_group or self.initial.get('group')

        if group_id:
            try:
                group_id = int(group_id)
                self.fields['chitti_member'].queryset = ChittiMember.objects.filter(
                    group_id=group_id
                ).select_related('member')
            except (ValueError, TypeError):
                self.fields['chitti_member'].queryset = ChittiMember.objects.none()
        else:
            self.fields['chitti_member'].queryset = ChittiMember.objects.none()

        # Optional: display member names properly
        self.fields['chitti_member'].label_from_instance = lambda obj: obj.member.name

    def save(self, commit=True):
        payment = super().save(commit=False)
        chitti_member = self.cleaned_data['chitti_member']

        payment.member = chitti_member.member
        payment.group = self.cleaned_data['group']

        if commit:
            payment.save()

        return payment
