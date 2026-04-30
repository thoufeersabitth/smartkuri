from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum
from datetime import date, timezone
from rest_framework.generics import ListAPIView
from chitti.models import ChittiGroup, ChittiMember
from collectors.api.v1.pagination import CollectorPagination
from collectors.api.v1.serializers import AssignedMemberSerializer
from payments.models import Payment
from members.models import Member
from accounts.models import StaffProfile
from django.db.models import Q
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.shortcuts import get_object_or_404
from datetime import datetime
from decimal import Decimal
from rest_framework import status
from django.utils import timezone
from datetime import timedelta
from collections import defaultdict


class CollectorDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        collector = request.user.staffprofile

        # Today date
        today = timezone.localdate()

        # =========================
        # TODAY COLLECTION
        # =========================
        today_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date=today,   # ✅ Direct filter (DateField)
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # =========================
        # MONTHLY COLLECTION
        # =========================
        monthly_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date__year=today.year,
            paid_date__month=today.month,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # =========================
        # TOTAL COLLECTION
        # =========================
        total_collection = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # =========================
        # ACTIVE MEMBERS
        # =========================
        active_members = Member.objects.filter(
            collections__collected_by=collector,
            collections__payment_status='success'
        ).distinct().count()

        # =========================
        # RECENT PAYMENTS
        # =========================
        recent_payments = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).order_by('-paid_date')[:10]

        recent_data = [
            {
                "member": payment.member.name,
                "amount": payment.amount,
                "date": payment.paid_date,
            }
            for payment in recent_payments
        ]

        return Response({
            "today_collection": today_collection,
            "monthly_collection": monthly_collection,
            "total_collection": total_collection,
            "active_members": active_members,
            "recent_payments": recent_data
        })

class ListMembersAPIView(ListAPIView):
    serializer_class = AssignedMemberSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CollectorPagination

    def get_queryset(self):
        staff = self.request.user.staffprofile

        queryset = Member.objects.filter(
            assigned_chitti_group__collector=staff
        )

        q = self.request.query_params.get('q')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q)
            )

        return queryset.order_by('name')
    

# ==================================================
# MEMBER HISTORY API (Collector)
# ==================================================


class MemberHistoryAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, member_id):

        staff = request.user.staffprofile
        current_date = timezone.now().date()

        member = get_object_or_404(
            Member,
            id=member_id,
            assigned_chitti_group__collector=staff
        )

        payments = Payment.objects.filter(
            member=member,
            payment_status='success'
        ).order_by('-paid_date')

        total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        group = member.assigned_chitti_group

        start_date = group.start_date if group.start_date else current_date

        total_months = group.duration_months
        monthly_amount = float(group.monthly_amount)
        total_kuri_amount = float(group.total_amount) if group.total_amount else (monthly_amount * total_months)

        temp_total_paid = float(total_paid)
        pending_amount = max(total_kuri_amount - temp_total_paid, 0)

        # ✅ Month-wise status
        month_status = []

        for i in range(1, total_months + 1):

            target = monthly_amount
            received = 0
            remaining = target

            month_due_date = start_date + timedelta(days=30 * (i - 1))
            is_future_month = month_due_date > current_date

            if temp_total_paid >= target:
                received = target
                remaining = 0
                status = "Advance" if is_future_month else "Full Paid"
                temp_total_paid -= target

            elif temp_total_paid > 0:
                received = temp_total_paid
                remaining = target - received
                status = "Partial"
                temp_total_paid = 0

            else:
                status = "Pending"

            month_status.append({
                "month": i,
                "target": target,
                "received": received,
                "remaining": remaining,
                "status": status
            })

        # ✅ Payment list
        payment_data = []

        for payment in payments:

            collected_by = None

            if payment.collected_by:
                if payment.collected_by.role == "collector":
                    collected_by = payment.collected_by.user.username
                elif payment.collected_by.role == "group_admin":
                    collected_by = "Group Admin"
                else:
                    collected_by = payment.collected_by.role.replace("_", " ").title()

            payment_data.append({
                "id": payment.id,
                "paid_date": payment.paid_date,
                "amount": payment.amount,
                "payment_method": payment.payment_method,
                "collected_by": collected_by
            })

        return Response({
            "member": {
                "id": member.id,
                "name": getattr(member, "name", None),
                "phone": getattr(member, "phone", None),
            },
            "summary": {
                "total_months": total_months,
                "monthly_amount": monthly_amount,
                "total_kuri_amount": total_kuri_amount,
                "total_paid": total_paid,
                "pending_amount": pending_amount,
            },
            "month_status": month_status,  # ✅ NEW
            "payments": payment_data
        })

# ==================================================
# ➕ Add Collection API (Collector)
# ==================================================
class AddCollectionAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            staff = request.user.staffprofile
        except:
            return Response(
                {"error": "Staff profile not found"},
                status=status.HTTP_400_BAD_REQUEST
            )

        member_id = request.data.get("member")
        amount = request.data.get("amount")
        paid_date_str = request.data.get("paid_date")
        method = request.data.get("payment_method")

        # -----------------------------
        # ✅ Required fields check
        # -----------------------------
        if not all([member_id, amount, paid_date_str, method]):
            return Response(
                {"error": "All fields are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ Member validation
        # -----------------------------
        member = get_object_or_404(
            Member,
            id=member_id,
            assigned_chitti_group__collector=staff
        )

        group = member.assigned_chitti_group

        # -----------------------------
        # ✅ Amount validation
        # -----------------------------
        try:
            amount = Decimal(amount)
            if amount <= 0:
                return Response(
                    {"error": "Amount must be greater than 0"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except:
            return Response(
                {"error": "Invalid amount format"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ Date convert (flexible)
        # -----------------------------
        paid_date = None
        formats = ["%d-%m-%Y", "%Y-%m-%d"]

        for fmt in formats:
            try:
                paid_date = datetime.strptime(paid_date_str, fmt).date()
                break
            except:
                continue

        if not paid_date:
            return Response(
                {"error": "Invalid date format"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ Duplicate check (same day)
        # -----------------------------
        if Payment.objects.filter(
            member=member,
            group=group,
            paid_date=paid_date,
            payment_status='success'
        ).exists():
            return Response(
                {"error": "Already payment exists for this date"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ LIMIT CHECK (IMPORTANT 🔥)
        # -----------------------------
        full_total_amount = Decimal(group.monthly_amount) * group.duration_months

        actual_paid = Payment.objects.filter(
            member=member,
            group=group,
            payment_status='success'
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

        if actual_paid + amount > full_total_amount:
            remaining = full_total_amount - actual_paid
            return Response(
                {"error": f"Only ₹{remaining} allowed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ CREATE PAYMENT (FULL FLOW)
        # -----------------------------
        Payment.objects.create(
            member=member,
            collected_by=staff,
            group=group,
            amount=amount,
            paid_date=paid_date,
            payment_method=method.lower(),
            payment_status='success',

            # 🔥 IMPORTANT FLAGS
            sent_to_admin=False,
            received_by_admin=False,
            admin_status='pending'
        )

        return Response(
            {
                "message": "Payment collected successfully ✅",
                "amount": float(amount),
                "member": member.name
            },
            status=status.HTTP_201_CREATED
        )



# -----------------------------
# 📤 Send Payments to Admin API
# -----------------------------
class SendToAdminAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        staff = request.user.staffprofile

        # Optional: group filter
        group_id = request.data.get("group_id")

        payments = Payment.objects.filter(
            collected_by=staff,
            payment_status='success',
            sent_to_admin=False,
            received_by_admin=False
        )

        # ✅ If group_id given → filter
        if group_id:
            payments = payments.filter(group_id=group_id)

        if not payments.exists():
            return Response(
                {"message": "No pending payments to send"},
                status=status.HTTP_200_OK
            )

        total_amount = payments.aggregate(
            total=Sum('amount')
        )['total'] or 0

        # ✅ Mark as sent
        payments.update(
            sent_to_admin=True,
            admin_status='pending'
        )

        return Response({
            "message": "Payments sent to admin successfully ✅",
            "total_amount": float(total_amount),
            "count": payments.count()
        }, status=status.HTTP_200_OK) 
    



class ResendSinglePaymentAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, payment_id):
        staff = request.user.staffprofile

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            collected_by=staff
        )

        # ❌ Only rejected allowed
        if payment.admin_status != 'rejected':
            return Response(
                {"error": "Only rejected payments can be resent"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔁 Reset & resend
        payment.admin_status = 'pending'
        payment.sent_to_admin = True
        payment.received_by_admin = False
        payment.save()

        return Response({
            "message": "Payment resent to admin successfully ✅",
            "payment_id": payment.id
        }, status=status.HTTP_200_OK)



class ResendGroupPaymentsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        staff = request.user.staffprofile
        group_id = request.data.get("group_id")

        if not group_id:
            return Response(
                {"error": "group_id is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        payments = Payment.objects.filter(
            collected_by=staff,
            group_id=group_id,
            admin_status='rejected'
        )

        if not payments.exists():
            return Response(
                {"message": "No rejected payments to resend"},
                status=status.HTTP_200_OK
            )

        count = payments.count()

        # ⚡ Bulk update (fast)
        payments.update(
            admin_status='pending',
            sent_to_admin=True,
            received_by_admin=False
        )

        return Response({
            "message": "All rejected payments resent successfully ✅",
            "total_resent": count
        }, status=status.HTTP_200_OK)
    
    
    
class TodayCollectionsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile

        payments = Payment.objects.filter(
            collected_by=staff,
            paid_date=date.today(),
            payment_status='success'
        ).order_by('-id')

        total_collected = payments.aggregate(total=Sum('amount'))['total'] or 0

        payment_data = [
            {
                "id": p.id,
                "member": p.member.name if p.member else None,  
                "amount": float(p.amount),
                "payment_method": p.payment_method,
                "paid_date": p.paid_date,
            }
            for p in payments
        ]

        return Response({
            "total_collected": total_collected,
            "payments": payment_data
        })
    

class AllCollectionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile
        today = date.today()

        payments = Payment.objects.filter(
            collected_by=staff,
            payment_status='success'
        ).select_related('member', 'group').order_by('-paid_date')

        payments_by_group = defaultdict(list)

        # 🔹 Group payments
        for payment in payments:
            payment.is_today = (payment.paid_date == today)
            payments_by_group[payment.group].append(payment)

        group_list = []

        for group, group_payments in payments_by_group.items():

            total_collector = sum(p.amount for p in group_payments)

            total_admin = sum(
                p.amount for p in group_payments
                if p.received_by_admin
            )

            sent = sum(
                p.amount for p in group_payments
                if p.sent_to_admin
            )

            draft = sum(
                p.amount for p in group_payments
                if not p.sent_to_admin
            )

            pending = sent - total_admin
            if pending < 0:
                pending = 0

            has_rejected = any(
                p.admin_status == "rejected"
                for p in group_payments
            )

            # 🔥 Serialize payments
            payments_data = []
            for p in group_payments:
                payments_data.append({
                    "payment_id": p.id,
                    "member_name": p.member.name if p.member else None,
                    "amount": float(p.amount),
                    "paid_date": p.paid_date,
                    "is_today": p.is_today,
                    "sent_to_admin": p.sent_to_admin,
                    "received_by_admin": p.received_by_admin,
                    "admin_status": p.admin_status
                })

            group_list.append({
                "group_id": group.id,
                "group_name": group.name,
                "total_collector": float(total_collector),
                "total_admin": float(total_admin),
                "pending": float(pending),
                "not_sent": float(draft),
                "has_rejected": has_rejected,
                "payments": payments_data
            })

        return Response({
            "groups": group_list
        })




class PendingMembersAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile
        today = timezone.now().date()
        status = request.GET.get('status', 'pending')  

        # Get all active members in collector's groups
        chitti_members = ChittiMember.objects.filter(
            group__collector=staff,
            group__is_active=True
        ).select_related('member', 'group')

        member_list = []

        for cm in chitti_members:
            group = cm.group

            current_month = (
                (today.year - group.start_date.year) * 12
                + (today.month - group.start_date.month)
                + 1
            )

            if current_month < 1 or current_month > group.duration_months:
                continue

            # Total paid this month
            paid_amount = Payment.objects.filter(
                member=cm.member,  # ✅ cm.member is Member
                group=group,
                paid_date__year=today.year,
                paid_date__month=today.month,
                payment_status='success'
            ).aggregate(total=Sum('amount'))['total'] or 0

            if status == "pending" and paid_amount < group.monthly_amount:
                member_list.append({
                    'member_name': cm.member.name,  # ✅ return name only
                    'member_id': cm.member.id,
                    'group': group.name,
                    'month': today.strftime('%B %Y'),
                    'paid': float(paid_amount),
                    'due': float(group.monthly_amount - paid_amount),
                    'status': 'Pending'
                })

            elif status == "success" and paid_amount >= group.monthly_amount:
                member_list.append({
                    'member_name': cm.member.name,
                    'member_id': cm.member.id,
                    'group': group.name,
                    'month': today.strftime('%B %Y'),
                    'paid': float(paid_amount),
                    'due': 0.0,
                    'status': 'Success'
                })

        return Response({
            "status_filter": status,
            "members": member_list
        })


# -----------------------------
# ✏️ Edit Payment API
# -----------------------------
class EditPaymentAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, payment_id):
        staff = request.user.staffprofile
        payment = get_object_or_404(
            Payment, id=payment_id, collected_by=staff
        )

        member_id = request.data.get("member")
        amount = request.data.get("amount")
        paid_date_str = request.data.get("paid_date")
        payment_method = request.data.get("payment_method")

        # Validate required fields
        if not all([member_id, amount, paid_date_str, payment_method]):
            return Response(
                {"error": "All fields are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate member
        member = get_object_or_404(
            Member,
            id=member_id,
            assigned_chitti_group__collector=staff
        )

        # Validate amount
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            return Response(
                {"error": "Invalid amount."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Flexible date parsing
        formats = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]
        paid_date = None

        for fmt in formats:
            try:
                paid_date = datetime.strptime(paid_date_str, fmt).date()
                break
            except ValueError:
                continue

        if not paid_date:
            return Response(
                {"error": "Invalid date format."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check duplicate monthly payment
        exists = Payment.objects.filter(
            member=member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month
        ).exclude(id=payment.id).exists()

        if exists:
            return Response(
                {"error": "This month payment already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Update payment
        payment.member = member
        payment.amount = amount
        payment.paid_date = paid_date
        payment.payment_method = payment_method
        payment.save()

        return Response(
            {"message": "Payment updated successfully"},
            status=status.HTTP_200_OK
        )
# -----------------------------
# 🗑️ Delete Payment API
# -----------------------------
class DeletePaymentAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, payment_id):
        staff = request.user.staffprofile
        today = timezone.now().date()

        payment = get_object_or_404(
            Payment,
            id=payment_id,
            collected_by=staff,
            paid_date=today
        )

        payment.delete()
        return Response({"message": "Payment deleted successfully"}, status=status.HTTP_200_OK)
    

class CollectorReportsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile
        today = date.today()

        # Base queryset
        qs = Payment.objects.filter(
            collected_by=staff,
            payment_status='success'
        ).select_related("member", "group")

        # Daily and monthly totals
        daily_total = qs.filter(paid_date=today).aggregate(total=Sum('amount'))['total'] or 0
        monthly_total = qs.filter(
            paid_date__year=today.year,
            paid_date__month=today.month
        ).aggregate(total=Sum('amount'))['total'] or 0

        # ================= Paid Members List =================
        from_date = request.GET.get('from')
        to_date = request.GET.get('to')

        if from_date or to_date:
            filtered_qs = qs
            if from_date:
                from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
                filtered_qs = filtered_qs.filter(paid_date__gte=from_date_obj)
            if to_date:
                to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
                filtered_qs = filtered_qs.filter(paid_date__lte=to_date_obj)
            paid_members = filtered_qs.order_by('-paid_date')
        else:
            paid_members = qs.filter(
                paid_date__year=today.year,
                paid_date__month=today.month
            ).order_by('-paid_date')

        members_list = [
            {
                "id": p.id,
                "member_name": p.member.name if p.member else None,
                "group": p.group.name if p.group else None,
                "amount": float(p.amount),
                "payment_method": p.payment_method,
                "paid_date": p.paid_date.strftime("%Y-%m-%d"),
            } for p in paid_members
        ]

        return Response({
            "daily_total": float(daily_total),
            "monthly_total": float(monthly_total),
            "paid_members": members_list,
            "from_date": from_date or None,
            "to_date": to_date or None
        })
    

class CollectorProfileAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        collector = request.user.staffprofile

        assigned_groups = ChittiGroup.objects.filter(collector=collector)
        group_names = [g.name for g in assigned_groups]

        return Response({
            "collector": {
                "id": collector.id,
                "username": collector.user.username,
                "phone": collector.phone,   
                "email": collector.user.email,
                "joined": collector.user.date_joined.strftime("%d %b %Y"),
            },
            "assigned_groups": group_names
        })