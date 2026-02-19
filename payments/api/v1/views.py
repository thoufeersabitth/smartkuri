from django.db.models import Sum
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError

from payments.models import Payment
from members.models import Member


# =====================================================
# 1️⃣ GROUP PAYMENT LIST API
# =====================================================
# =====================================================
# 1️⃣ GROUP PAYMENT LIST API (Enhanced)
# =====================================================
class GroupPaymentListAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        staff_profile = getattr(request.user, "staffprofile", None)

        if not staff_profile or not staff_profile.group:
            return Response(
                {"error": "No group assigned"},
                status=status.HTTP_400_BAD_REQUEST
            )

        main_group = staff_profile.group
        groups = [main_group.id] + list(
            main_group.sub_groups.values_list("id", flat=True)
        )

        payments = Payment.objects.filter(group_id__in=groups) \
            .select_related('member', 'collected_by', 'group') \
            .order_by('-paid_date')

        total_collected = payments.filter(
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        def get_collector_name(profile):
            if not profile:
                return None
            if profile.role == "admin":
                return "Admin"
            elif profile.role == "group_admin":
                return "Group Admin"
            else:
                return profile.user.username

        data = [
            {
                "id": p.id,
                "member": p.member.name,
                "amount": p.amount,
                "paid_date": p.paid_date,
                "status": p.payment_status,
                "payment_method": getattr(p, "payment_method", None),
                "collected_by": get_collector_name(p.collected_by)
            }
            for p in payments
        ]

        return Response({
            "total_collected": total_collected,
            "count": payments.count(),
            "payments": data
        })



# =====================================================
# 2️⃣ GROUP PAYMENT CREATE API
# =====================================================
class GroupPaymentCreateAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        member_id = request.data.get("member")
        amount = request.data.get("amount")

        if not member_id or not amount:
            raise ValidationError("Member and amount required")

        try:
            member = Member.objects.get(id=member_id)
        except Member.DoesNotExist:
            raise ValidationError("Invalid member")

        group = member.assigned_chitti_group
        if not group:
            raise ValidationError("Member not assigned to group")

        paid_date = timezone.now().date()

        already_paid = Payment.objects.filter(
            member=member,
            group=group,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month,
            payment_status='success'
        ).exists()

        if already_paid:
            raise ValidationError("Member already paid this month")

        payment = Payment.objects.create(
            member=member,
            group=group,
            amount=amount,
            paid_date=paid_date,
            payment_status="success",
            collected_by=request.user.staffprofile
        )

        return Response({
            "message": "Payment created successfully",
            "payment_id": payment.id
        }, status=status.HTTP_201_CREATED)


# =====================================================
# 3️⃣ GROUP PAYMENT EDIT API
# =====================================================
class GroupPaymentEditAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request, pk):

        try:
            payment = Payment.objects.get(
                pk=pk,
                collected_by=request.user.staffprofile
            )
        except Payment.DoesNotExist:
            return Response(
                {"error": "Payment not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        payment.amount = request.data.get("amount", payment.amount)
        payment.payment_status = request.data.get(
            "payment_status", payment.payment_status
        )

        payment.save()

        return Response({"message": "Payment updated successfully"})


# =====================================================
# 4️⃣ GROUP PAYMENT DELETE API
# =====================================================
class GroupPaymentDeleteAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):

        try:
            payment = Payment.objects.get(
                pk=pk,
                collected_by=request.user.staffprofile
            )
        except Payment.DoesNotExist:
            return Response(
                {"error": "Payment not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        payment.delete()

        return Response(
            {"message": "Payment deleted successfully"},
            status=status.HTTP_204_NO_CONTENT
        )


#