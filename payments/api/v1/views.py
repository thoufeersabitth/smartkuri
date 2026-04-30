from collections import defaultdict

from django.db.models import Sum
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from chitti.models import ChittiGroup
from payments.models import Payment
from members.models import Member
from chitti.models import ChittiGroup, ChittiMember
from django.core.paginator import Paginator
from rest_framework_simplejwt.authentication import JWTAuthentication

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

        # ❌ No group check
        if not staff_profile or not staff_profile.group:
            return Response(
                {"error": "You are not assigned to any group."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Main group
        main_group = staff_profile.group

        # ✅ Include subgroups
        group_ids = [main_group.id] + list(
            main_group.sub_groups.values_list('id', flat=True)
        )

        # ✅ Fetch payments
        payments_qs = Payment.objects.filter(group_id__in=group_ids) \
            .select_related('member', 'collected_by', 'group') \
            .order_by('-paid_date')

        # =====================================================
        # 🔥 TOTALS
        # =====================================================
        total_collector_collected = payments_qs.filter(
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        total_admin_collected = payments_qs.filter(
            payment_status='success',
            received_by_admin=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        # =====================================================
        # 🔥 PAGINATION (FIXED)
        # =====================================================
        page_number = request.GET.get('page', 1)

        paginator = Paginator(payments_qs, 10)  # ✅ FIXED
        page_obj = paginator.get_page(page_number)

        # =====================================================
        # 🔥 FORMAT DATA
        # =====================================================
        def get_collector_name(profile):
            if not profile:
                return None
            if profile.role == "admin":
                return "Admin"
            elif profile.role == "group_admin":
                return "Group Admin"
            return profile.user.username

        payments_data = [
            {
                "id": p.id,
                "member": p.member.name,
                "group": p.group.name if hasattr(p.group, "name") else p.group.id,
                "amount": float(p.amount),
                "paid_date": p.paid_date,
                "status": p.payment_status,
                "payment_method": getattr(p, "payment_method", None),
                "collected_by": get_collector_name(p.collected_by),
                "received_by_admin": getattr(p, "received_by_admin", False)
            }
            for p in page_obj
        ]

        # =====================================================
        # ✅ FINAL RESPONSE
        # =====================================================
        return Response({
            "total_collector_collected": float(total_collector_collected),
            "total_admin_collected": float(total_admin_collected),

            "pagination": {
                "current_page": page_obj.number,
                "total_pages": paginator.num_pages,
                "total_items": paginator.count,
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
            },

            "payments": payments_data

        }, status=status.HTTP_200_OK)

class GroupPaymentCreateAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        group_id = request.data.get("group")
        member_id = request.data.get("member")
        amount = request.data.get("amount")

        # =========================
        # VALIDATION
        # =========================
        if not group_id or not member_id or not amount:
            return Response(
                {"error": "group, member, amount required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            group = ChittiGroup.objects.get(id=group_id)
        except ChittiGroup.DoesNotExist:
            return Response({"error": "Invalid group"}, status=400)

        try:
            member = Member.objects.get(id=member_id)
        except Member.DoesNotExist:
            return Response({"error": "Invalid member"}, status=400)

        staff_profile = getattr(request.user, "staffprofile", None)
        if not staff_profile:
            return Response({"error": "Collector profile not found"}, status=400)

        # =========================
        # AUTO ADD CHITTI MEMBER (SAFE)
        # =========================
        chitti_member, created = ChittiMember.objects.get_or_create(
            member=member,
            group=group,
            defaults={
                "token_no": (
                    ChittiMember.objects.filter(group=group)
                    .aggregate(max_token=Sum("token_no"))["max_token"] or 0
                ) + 1
            }
        )

        # =========================
        # CREATE PAYMENT
        # =========================
        payment = Payment.objects.create(
            member=member,
            group=group,
            amount=amount,
            paid_date=timezone.now().date(),
            payment_status="success",
            collected_by=staff_profile
        )

        # =========================
        # CALCULATION LOGIC (YOUR VIEW)
        # =========================
        current_month_no = int(group.current_month)
        monthly_rate = float(group.monthly_amount)
        total_expected_to_date = current_month_no * monthly_rate

        actual_paid = float(
            Payment.objects.filter(
                member=member,
                group=group,
                payment_status='success'
            ).aggregate(total=Sum('amount'))['total'] or 0
        )

        months_covered = int(actual_paid // monthly_rate)
        next_installment = months_covered + 1

        pending = max(0, total_expected_to_date - actual_paid)
        advance = max(0, actual_paid - total_expected_to_date)

        # =========================
        # STATUS LOGIC
        # =========================
        if pending > 0:
            status_label = f"Due: ₹{pending:.2f}"
            is_advance_mode = False

        elif actual_paid >= total_expected_to_date:
            status_label = f"Advance: ₹{advance:.2f} (Month {next_installment} Next)"
            is_advance_mode = True

        else:
            status_label = "Up to date ✅"
            is_advance_mode = False

        # =========================
        # MEMBER RESPONSE DATA (like your template loop)
        # =========================
        members = []

        group_members = ChittiMember.objects.filter(
            group=group
        ).select_related("member")

        for cm in group_members:

            total_paid_member = float(
                Payment.objects.filter(
                    member=cm.member,
                    group=group,
                    payment_status='success'
                ).aggregate(total=Sum('amount'))['total'] or 0
            )

            months_covered_m = int(total_paid_member // monthly_rate)
            next_installment_m = months_covered_m + 1

            pending_m = max(0, total_expected_to_date - total_paid_member)
            advance_m = max(0, total_paid_member - total_expected_to_date)

            if pending_m > 0:
                status_label_m = f"Due: ₹{pending_m:.2f}"
                is_advance_mode_m = False
            elif total_paid_member >= total_expected_to_date:
                status_label_m = f"Advance: ₹{advance_m:.2f} (Month {next_installment_m} Next)"
                is_advance_mode_m = True
            else:
                status_label_m = "Up to date ✅"
                is_advance_mode_m = False

            members.append({
                "member_id": cm.member.id,
                "name": cm.member.name,
                "token_no": cm.token_no,
                "monthly_target": monthly_rate,
                "total_paid": total_paid_member,
                "pending": pending_m,
                "advance": advance_m,
                "next_installment": next_installment_m,
                "status_label": status_label_m,
                "is_advance_mode": is_advance_mode_m,
            })

        # =========================
        # FINAL RESPONSE
        # =========================
        return Response({
            "message": "Payment created successfully",
            "payment_id": payment.id,

            "group": group.id,
            "member": member.id,

            "monthly_target": monthly_rate,
            "total_paid": actual_paid,
            "pending": pending,
            "advance": advance,
            "next_installment": next_installment,
            "status_label": status_label,
            "is_advance_mode": is_advance_mode,

            "members": members
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




from collections import defaultdict
from django.db import transaction
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from chitti.models import ChittiGroup
from payments.models import Payment


# ============================================
# 🔥 ADMIN PENDING PAYMENTS API
# ============================================
class AdminPendingPaymentsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):

        staff = getattr(request.user, "staffprofile", None)

        if not staff:
            return Response({"error": "No staff profile"}, status=400)

        # 🔹 Role-based group access
        if staff.role == 'admin':
            groups = ChittiGroup.objects.all()

        elif staff.role == 'group_admin':
            main_groups = ChittiGroup.objects.filter(owner=staff.user)
            sub_groups = ChittiGroup.objects.filter(parent_group__in=main_groups)
            groups = (main_groups | sub_groups).distinct()

        else:
            return Response({"error": "Not authorized"}, status=403)

        payments = Payment.objects.filter(
            payment_status='success',
            group__in=groups,
            collected_by__isnull=False,
            collected_by__role='collector',
            sent_to_admin=True
        ).select_related('member', 'group', 'collected_by') \
         .order_by('-paid_date', '-id')

        grouped = defaultdict(list)

        for p in payments:
            grouped[p.group].append(p)

        group_list = []

        for group, group_payments in grouped.items():

            pending = [p for p in group_payments if p.admin_status == 'pending']
            approved = [p for p in group_payments if p.admin_status == 'approved']
            rejected = [p for p in group_payments if p.admin_status == 'rejected']

            group_list.append({
                "group_id": group.id,
                "group_name": group.name,

                "total_pending": sum(p.amount for p in pending),
                "total_approved": sum(p.amount for p in approved),
                "total_rejected": sum(p.amount for p in rejected),

                "count_pending": len(pending),
                "count_approved": len(approved),
                "count_rejected": len(rejected),

                "pending_payments": [
                    {
                        "id": p.id,
                        "member": p.member.name,
                        "amount": p.amount,
                        "date": p.paid_date
                    } for p in pending
                ],
            })

        return Response({"groups": group_list})


# ============================================
# 🔥 GROUP PAYMENT DETAILS API
# ============================================
class GroupPaymentDetailsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, group_id):

        staff = getattr(request.user, "staffprofile", None)

        if not staff:
            return Response({"error": "No staff profile"}, status=400)

        if staff.role == 'admin':
            group = get_object_or_404(ChittiGroup, id=group_id)

        elif staff.role == 'group_admin':
            group = get_object_or_404(
                ChittiGroup,
                id=group_id,
                owner=staff.user
            )
        else:
            return Response({"error": "Not allowed"}, status=403)

        payments = Payment.objects.filter(
            group=group,
            payment_status='success',
            collected_by__isnull=False,
            collected_by__role='collector',
            sent_to_admin=True
        ).select_related('member', 'collected_by__user') \
         .order_by('-paid_date')

        data = [
            {
                "id": p.id,
                "member": p.member.name,
                "amount": p.amount,
                "paid_date": p.paid_date,
                "collector": p.collected_by.user.username,
                "status": p.admin_status
            }
            for p in payments
        ]

        return Response({
            "group_id": group.id,
            "group_name": group.name,
            "payments": data
        })


# ============================================
# 🔥 SINGLE PAYMENT APPROVE API
# ============================================
class ApprovePaymentAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, payment_id):

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            sent_to_admin=True
        )

        if payment.admin_status == 'approved':
            return Response({"message": "Already approved"})

        payment.admin_status = 'approved'
        payment.is_seen = True   # 🔔 remove notification
        payment.save()

        # 🔥 Prevent duplicate allocation
        if not payment.allocations.exists():
            payment.allocate_payment()

        return Response({
            "message": f"Payment ₹{payment.amount} approved"
        })


# ============================================
# 🔥 SINGLE PAYMENT REJECT API
# ============================================
class RejectPaymentAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, payment_id):

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            sent_to_admin=True
        )

        if payment.admin_status == 'rejected':
            return Response({"message": "Already rejected"})

        # 🔥 If already approved → reverse allocation
        if payment.admin_status == 'approved':
            payment.reverse_allocation()

        payment.admin_status = 'rejected'
        payment.is_seen = True   # 🔔 remove notification
        payment.save()

        return Response({
            "message": f"Payment ₹{payment.amount} rejected"
        })


# ============================================
# 🔥 GROUP APPROVE API
# ============================================
class ApproveGroupPaymentsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, group_id):

        payments = Payment.objects.filter(
            group_id=group_id,
            payment_status='success',
            admin_status='pending',
            sent_to_admin=True
        )

        total = payments.aggregate(total=Sum('amount'))['total'] or 0

        if total == 0:
            return Response({"message": "No pending payments"})

        for p in payments:
            p.admin_status = 'approved'
            p.is_seen = True
            p.save()

            if not p.allocations.exists():
                p.allocate_payment()

        return Response({
            "message": "All payments approved",
            "total_amount": total
        })


# ============================================
# 🔥 GROUP REJECT API
# ============================================
class RejectGroupPaymentsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, group_id):

        payments = Payment.objects.filter(
            group_id=group_id,
            payment_status='success',
            admin_status='pending',
            sent_to_admin=True
        )

        total = payments.aggregate(total=Sum('amount'))['total'] or 0

        if total == 0:
            return Response({"message": "No pending payments"})

        for p in payments:
            if p.admin_status == 'approved':
                p.reverse_allocation()

            p.admin_status = 'rejected'
            p.is_seen = True
            p.save()

        return Response({
            "message": "All payments rejected",
            "total_amount": total
        })


# ============================================
# 🔔 ADMIN NOTIFICATION API
# ============================================
from django.db.models import Sum, Count, F
def get_all_subgroup_ids(group):
    ids = [group.id]
    children = group.sub_groups.all()

    for child in children:
        ids.extend(get_all_subgroup_ids(child))

    return ids


class AdminNotificationAPI(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):

        staff = request.user.staffprofile

        if staff.role not in ["admin", "group_admin"]:
            return Response({
                "pending_groups": [],
                "total_pending_count": 0
            })

        qs = Payment.objects.filter(
            sent_to_admin=True,
            admin_status__iexact='pending',
            is_seen=False
        )

        # 🔥 group_admin → main + all subgroups
        if staff.role == "group_admin" and staff.group:
            all_group_ids = get_all_subgroup_ids(staff.group)
            qs = qs.filter(group_id__in=all_group_ids)

        pending_groups = list(
            qs.values(
                'group__id',
                'group__name'
            ).annotate(
                total_pending=Sum('amount'),
                entry_count=Count('id')
            )
        )

        return Response({
            "pending_groups": pending_groups,
            "total_pending_count": qs.count()
        })