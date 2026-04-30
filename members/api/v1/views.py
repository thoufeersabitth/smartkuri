from datetime import timezone
import random
import string
from django.utils import timezone
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q, Max
from django.db.models import Sum
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication

from chitti.api.v1.serializers import AuctionSerializer
from members.models import Member
from chitti.models import Auction, ChittiGroup, ChittiMember
from payments.api.v1.serializers import PaymentSerializer
from payments.models import Payment
from subscriptions.utils import can_add_member

from .serializers import (
    MemberSerializer,
    MemberCreateSerializer
)
# MEMBER LIST (Group Admin)
class MemberListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = ChittiGroup.objects.filter(owner=request.user)

        members = Member.objects.filter(
            assigned_chitti_group__in=groups
        ).select_related("assigned_chitti_group", "user").order_by("id")

        q = request.GET.get("q")
        if q:
            members = members.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q) |
                Q(assigned_chitti_group__name__icontains=q)
            )

        return Response({
            "count": members.count(),
            "results": MemberSerializer(members, many=True).data
        })




# MEMBER CREATE (Group Admin)
class MemberCreateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        serializer = MemberCreateSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        group = data.get("assigned_chitti_group")

        # 🔒 Check group limit
        if group and not can_add_member(group):
            return Response(
                {"detail": "Group limit reached or subscription expired"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =============================
        # 👤 CREATE USER
        # =============================
        username = data.get("phone") or data.get("email")
        password = data["password"]

        user = User.objects.create_user(
            username=username,
            password=password,
            email=data.get("email")
        )

        # =============================
        # 👤 CREATE MEMBER
        # =============================
        member = Member.objects.create(
            user=user,
            name=data.get("name"),
            email=data.get("email"),
            phone=data.get("phone"),
            address=data.get("address"),
            aadhaar_no=data.get("aadhaar_no"),
            assigned_chitti_group=group,
            is_first_login=True
        )

        # =============================
        # 🎟️ SAFE TOKEN CREATION
        # =============================
        if group:
            for _ in range(3):  # retry max 3 times
                try:
                    last_token = ChittiMember.objects.filter(group=group).aggregate(
                        max_token=Max("token_no")
                    )["max_token"] or 0

                    next_token = last_token + 1

                    ChittiMember.objects.create(
                        group=group,
                        member=member,
                        token_no=next_token
                    )
                    break

                except Exception:
                    # retry if duplicate token issue
                    continue

        # =============================
        # ✅ RESPONSE
        # =============================
        return Response({
            "message": "Member created successfully",
            "username": username,
            "password": password,
            "group_id": group.id if group else None
        }, status=status.HTTP_201_CREATED)

# MEMBER UPDATE (Group Admin)
class MemberUpdateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        member = get_object_or_404(
            Member,
            pk=pk,
            assigned_chitti_group__owner=request.user
        )

        # Allowed fields only
        allowed_fields = ["name", "email", "phone", "address", "aadhaar_no"]

        data = {}
        for field in allowed_fields:
            if field in request.data:
                data[field] = request.data[field]

        serializer = MemberSerializer(member, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({"message": "Member updated successfully"})
    

# MEMBER DELETE (Group Admin)
class MemberDeleteAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        member = get_object_or_404(
            Member,
            pk=pk,
            assigned_chitti_group__owner=request.user
        )
        member.delete()
        return Response({"message": "Member deleted"})
    


class MemberDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        member_record = get_object_or_404(
            ChittiMember,
            member__id=pk,
            group__owner=request.user
        )

        member = member_record.member
        group = member_record.group

        monthly_amount = float(group.monthly_amount)
        duration = int(group.duration_months)
        current_grp_month = int(group.current_month)

        payments = list(
            Payment.objects.filter(
                member=member,
                group=group,
                payment_status="success"
            ).order_by("paid_date", "created_at")
        )

        # -----------------------------
        # CALCULATION (ADVANCED)
        # -----------------------------
        total_paid = float(sum(p.amount for p in payments))
        temp_balance = total_paid

        month_wise = []

        for month in range(1, duration + 1):
            target = monthly_amount
            allocated = 0

            if temp_balance >= target:
                allocated = target
                temp_balance -= target
                status = "Paid"
            elif temp_balance > 0:
                allocated = temp_balance
                temp_balance = 0
                status = "Partial"
            else:
                status = "Pending"

            month_wise.append({
                "month": month,
                "target": target,
                "paid": allocated,
                "balance": target - allocated,
                "status": status,
                "is_advance": month > current_grp_month and allocated > 0
            })

        # -----------------------------
        # RESPONSE
        # -----------------------------
        return Response({
            "member_details": {
                "name": member.name,
                "email": member.email,
                "phone": member.phone,
                "address": member.address,
                "aadhaar_no": member.aadhaar_no,
                "chitti_group": group.name,
                "monthly_amount": monthly_amount,
                "status": member.member_status
            },

            "financial_summary": {
                "total_paid": total_paid,
                "total_due": max(0, (current_grp_month * monthly_amount) - total_paid),
                "months_paid": sum(1 for m in month_wise if m["status"] == "Paid"),
                "duration_months": duration
            },

            "month_wise_payments": month_wise,

            "recent_transactions": [
                {
                    "amount": p.amount,
                    "paid_date": p.paid_date,
                    "collector": (
                        p.collected_by.user.get_full_name()
                        if p.collected_by else "Admin"
                    )
                }
                for p in payments
            ]
        })




# -----------------------------
# Helper: Generate random password
# -----------------------------
def generate_random_password(length=8):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


# -----------------------------
# Member Dashboard
# -----------------------------
class MemberDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_object_or_404(Member.objects.select_related('assigned_chitti_group'), user=request.user)

        payments = Payment.objects.filter(member=member)
        total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

        group = member.assigned_chitti_group
        total_amount = getattr(group, 'total_amount', 0)
        remaining = total_amount - total_paid

        auctions = Auction.objects.filter(group=group, winner__isnull=False).order_by('auction_date')
        latest_auction = auctions.last()
        is_winner = auctions.filter(winner__member=member).exists()

        return Response({
            "member": MemberSerializer(member).data,
            "total_paid": total_paid,
            "total_amount": total_amount,
            "remaining": remaining,
            "auctions": AuctionSerializer(auctions, many=True).data,
            "latest_auction": AuctionSerializer(latest_auction).data if latest_auction else None,
            "is_winner": is_winner
        })


# -----------------------------
# Member Profile
# -----------------------------
class MemberProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_object_or_404(Member, user=request.user)
        return Response(MemberSerializer(member).data)


# -----------------------------
# Member Payment History
class MemberPaymentsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):

        # ✅ Member
        member = get_object_or_404(Member, user=request.user)

        # ✅ Group
        member_record = (
            ChittiMember.objects
            .filter(member=member)
            .select_related('group')
            .first()
        )

        if not member_record:
            return Response(
                {"message": "No subscriptions found"},
                status=status.HTTP_200_OK
            )

        group = member_record.group

        # ✅ Payments
        payments_qs = (
            Payment.objects
            .filter(
                member=member,
                group=group,
                payment_status="success"
            )
            .select_related('collected_by__user')
            .order_by("paid_date", "created_at")
        )

        monthly_amount = float(group.monthly_amount)
        duration = int(group.duration_months)
        current_grp_month = int(group.current_month)

        total_paid = float(
            payments_qs.aggregate(total=Sum("amount"))["total"] or 0
        )

        payment_rows = []
        payments_list = list(payments_qs)

        overflow_cash = 0.0
        active_payment = None

        # 🔥 SAME LOGIC AS HTML
        for month in range(1, duration + 1):

            target = monthly_amount
            allocated_for_month = 0.0
            month_transactions = []

            while target > 0:

                if overflow_cash <= 0:
                    if payments_list:
                        active_payment = payments_list.pop(0)
                        overflow_cash = float(active_payment.amount)
                    else:
                        break

                take = min(overflow_cash, target)
                allocated_for_month += take

                # collector name
                collector_display = "Admin"
                if active_payment.collected_by:
                    user_obj = active_payment.collected_by.user
                    collector_display = (
                        user_obj.get_full_name() or user_obj.username
                    )

                month_transactions.append({
                    "amount": take,
                    "date": active_payment.paid_date,
                    "collector": collector_display
                })

                overflow_cash -= take
                target -= take

            # ✅ Status
            if allocated_for_month >= monthly_amount:
                status_label = "Paid"
            elif allocated_for_month > 0:
                status_label = "Partial"
            else:
                status_label = "Pending"

            payment_rows.append({
                "month": month,
                "target": monthly_amount,
                "paid": allocated_for_month,
                "balance": monthly_amount - allocated_for_month,
                "status": status_label,
                "transactions": month_transactions,
                "is_advance": month > current_grp_month and allocated_for_month > 0
            })

        # ✅ Summary
        total_due = max(
            0.0,
            (current_grp_month * monthly_amount) - total_paid
        )

        collections_paid = sum(
            1 for p in payment_rows if p["status"] == "Paid"
        )

        return Response({
            "group": {
                "id": group.id,
                "name": group.name,
                "monthly_amount": monthly_amount,
                "duration": duration,
                "current_month": current_grp_month
            },
            "summary": {
                "total_paid": total_paid,
                "total_due": total_due,
                "collections_paid": collections_paid
            },
            "payment_rows": payment_rows
        }, status=status.HTTP_200_OK)

# -----------------------------
# Member Auction List
# -----------------------------


class MemberAuctionsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):

        # ✅ Get member with group
        member = get_object_or_404(
            Member.objects.select_related('assigned_chitti_group'),
            user=request.user
        )

        # ✅ Check group
        if not member.assigned_chitti_group:
            return Response(
                {"error": "You are not assigned to any chitti group"},
                status=status.HTTP_400_BAD_REQUEST
            )

        group = member.assigned_chitti_group

        # ✅ Fetch auctions (optimized)
        auctions_qs = (
            Auction.objects
            .filter(group=group)
            .select_related('group', 'winner__member__user')
            .order_by('auction_date')
        )

        return Response({
            "member": {
                "id": member.id,
                "name": member.name,
            },
            "group": {
                "id": group.id,
                "name": group.name,
            },
            "today": timezone.now().date(),
            "auctions": AuctionSerializer(auctions_qs, many=True).data
        }, status=status.HTTP_200_OK)