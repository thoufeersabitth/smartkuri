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

class CollectorDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        collector = request.user.staffprofile

        # Today collection
        today_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date=date.today(),
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Monthly collection
        monthly_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date__month=date.today().month,
            paid_date__year=date.today().year,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Total collection
        total_collection = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Active members
        active_members = Member.objects.filter(
            collections__collected_by=collector
        ).distinct().count()

        # Recent 10 payments
        recent_payments = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).order_by('-paid_date', '-paid_time')[:10]

        recent_data = [
            {
                "member": payment.member.name,
                "amount": payment.amount,
                "date": payment.paid_date,
                "time": payment.paid_time
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

        # Logged-in staff
        staff = request.user.staffprofile

        # Get member under this collector
        member = get_object_or_404(
            Member,
            id=member_id,
            assigned_chitti_group__collector=staff
        )

        # Get successful payments
        payments = Payment.objects.filter(
            member=member,
            payment_status='success'
        ).order_by('-paid_date')

        total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

        group = member.assigned_chitti_group

        total_months = group.duration_months
        monthly_amount = group.monthly_amount
        total_kuri_amount = group.total_amount
        pending_amount = max(total_kuri_amount - total_paid, 0)

        # Payment list with role logic
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
            "payments": payment_data
        })
    

    # ==================================================
# ➕ Add Collection API (Collector)
# ==================================================
class AddCollectionAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        staff = request.user.staffprofile

        member_id = request.data.get("member")
        amount = request.data.get("amount")
        paid_date_str = request.data.get("paid_date")
        method = request.data.get("payment_method")

        # Validate member exists under this collector
        member = get_object_or_404(
            Member,
            id=member_id,
            assigned_chitti_group__collector=staff
        )

        # Validate amount
        try:
            amount = Decimal(amount)
            if amount <= 0:
                return Response({"error": "Invalid amount"}, status=status.HTTP_400_BAD_REQUEST)
        except:
            return Response({"error": "Invalid amount format"}, status=status.HTTP_400_BAD_REQUEST)

        # Convert date
        try:
            paid_date = datetime.strptime(paid_date_str, "%Y-%m-%d").date()
        except:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        # Check monthly duplicate
        exists = Payment.objects.filter(
            member=member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month
        ).exists()

        if exists:
            return Response({"error": "Payment for this month already collected"}, status=status.HTTP_400_BAD_REQUEST)

        # Create payment
        Payment.objects.create(
            member=member,
            collected_by=staff,
            group=member.assigned_chitti_group,
            amount=amount,
            paid_date=paid_date,
            payment_method=method,
            payment_status='success'
        )

        return Response({"message": "Payment collected successfully"}, status=status.HTTP_201_CREATED)
    


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
        payment = get_object_or_404(Payment, id=payment_id, collected_by=staff)

        member_id = request.data.get("member")
        amount = request.data.get("amount")
        paid_date_str = request.data.get("paid_date")
        payment_method = request.data.get("payment_method")

        # Validate member
        member = get_object_or_404(Member, id=member_id, assigned_chitti_group__collector=staff)

        # Parse date
        try:
            paid_date = datetime.strptime(paid_date_str, "%Y-%m-%d").date()
        except:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        # Check monthly duplicate (skip current payment)
        exists = Payment.objects.filter(
            member=member,
            paid_date__year=paid_date.year,
            paid_date__month=paid_date.month
        ).exclude(id=payment.id).exists()

        if exists:
            return Response({"error": "This month payment already exists."}, status=status.HTTP_400_BAD_REQUEST)

        # Update payment
        payment.member = member
        payment.amount = amount
        payment.paid_date = paid_date
        payment.payment_method = payment_method
        payment.save()

        return Response({"message": "Payment updated successfully"}, status=status.HTTP_200_OK)


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

        # Only group names
        assigned_groups = ChittiGroup.objects.filter(collector=collector)
        group_names = [g.name for g in assigned_groups]

        return Response({
            "collector": {
                "id": collector.id,
                "username": collector.user.username,
                "phone": collector.user.phone if hasattr(collector.user, 'phone') else "",
                "email": collector.user.email,
                "joined": collector.user.date_joined.strftime("%d %b %Y"),
            },
            "assigned_groups": group_names
        })