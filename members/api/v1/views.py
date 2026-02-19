from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from django.db.models import Q

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.authentication import JWTAuthentication

from members.models import Member
from chitti.models import ChittiGroup, ChittiMember
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

        serializer = MemberSerializer(member, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        new_group = serializer.validated_data.get("assigned_chitti_group")
        if new_group and new_group != member.assigned_chitti_group:
            if not can_add_member(new_group):
                return Response(
                    {"detail": "New group limit reached"},
                    status=status.HTTP_400_BAD_REQUEST
                )

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

        group = member_record.group
        duration_months = group.duration_months

        payments = list(
            Payment.objects.filter(
                member=member_record.member,
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
            "member": {
                "id": member_record.member.id,
                "name": member_record.member.name,
                "token_no": member_record.token_no,
                "group": group.name,
            },
            "total_collected": sum(p.amount for p in payments),
            "total_due": member_record.pending_amount,
            "months_paid": index,
            "duration_months": duration_months,
            "month_wise": month_wise
        })
