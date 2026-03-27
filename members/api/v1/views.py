import random
import string

from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.db.models import Sum

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

        # 👤 Create Django User
        username = data.get("phone") or data.get("email")
        password = data["password"]

        user = User.objects.create_user(
            username=username,
            password=password,
            email=data.get("email")
        )

        # 👤 Create Member
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

        # 🎟️ Token create
        if group:
            last_token = (
                ChittiMember.objects
                .filter(group=group)
                .values_list("token_no", flat=True)
            )
            next_token = max(last_token, default=0) + 1

            ChittiMember.objects.create(
                group=group,
                member=member,
                token_no=next_token
            )

        return Response({
            "message": "Member created successfully",
            "username": username,
            "password": password
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
    

# members_read (Group Admin)
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
        duration_months = group.duration_months

        payments = list(
            Payment.objects.filter(
                member=member,
                group=group,
                payment_status="success"
            ).order_by("paid_date")
        )

        month_wise = []
        index = 0

        for month in range(1, duration_months + 1):
            if index < len(payments):
                p = payments[index]

                month_wise.append({
                    "month": month,
                    "amount": p.amount,
                    "paid_date": p.paid_date,
                    "collector": (
                        p.collected_by.user.get_full_name()
                        if p.collected_by else "Admin"
                    ),
                    "status": "Paid"
                })

                index += 1
            else:
                month_wise.append({
                    "month": month,
                    "amount": None,
                    "paid_date": None,
                    "collector": None,
                    "status": "Pending"
                })

        return Response({
            "member_details": {
                "name": member.name,
                "email": member.email,
                "phone": member.phone,
                "address": member.address,
                "aadhaar_no": member.aadhaar_no,
                "chitti_group": group.name,
                "monthly_amount": group.monthly_amount,
                "status": member.member_status
            },

            "financial_summary": {
                "total_collected": sum(p.amount for p in payments),
                "pending_amount": member.pending_amount,
                "months_paid": index,
                "duration_months": duration_months
            },

            "month_wise_payments": month_wise
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
# -----------------------------
class MemberPaymentsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_object_or_404(Member, user=request.user)
        payments_qs = Payment.objects.filter(member=member).select_related("collected_by__user").order_by("-paid_date")
        total_paid = payments_qs.filter(payment_status="success").aggregate(total=Sum('amount'))['total'] or 0

        return Response({
            "total_paid": total_paid,
            "payments": PaymentSerializer(payments_qs, many=True).data
        })


# -----------------------------
# Member Auction List
# -----------------------------
class MemberAuctionsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_object_or_404(Member.objects.select_related('assigned_chitti_group'), user=request.user)

        if not member.assigned_chitti_group:
            return Response({"error": "You are not assigned to any chitti group"}, status=status.HTTP_400_BAD_REQUEST)

        auctions_qs = Auction.objects.filter(group=member.assigned_chitti_group).select_related('winner__member').order_by('auction_date')
        return Response(AuctionSerializer(auctions_qs, many=True).data)