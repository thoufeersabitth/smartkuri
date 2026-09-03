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





# SEARCH EXISTING MEMBER (Group Admin)
class SearchExistingMemberAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        query = request.GET.get("q", "").strip() or request.GET.get("identifier", "").strip()
        if not query or len(query) < 2:
            return Response({"exists": False, "results": []})

        # Search Members matching query
        members_qs = Member.objects.filter(
            Q(email__icontains=query) | Q(phone__icontains=query) | Q(name__icontains=query)
        ).select_related("user", "assigned_chitti_group")[:10]

        results = []
        seen_user_ids = set()

        for m in members_qs:
            uid = m.user_id if m.user else None
            if uid and uid in seen_user_ids:
                continue
            if uid:
                seen_user_ids.add(uid)
            results.append({
                "id": m.id,
                "user_id": uid,
                "name": m.name,
                "email": m.email or "",
                "phone": m.phone or "",
                "address": m.address or "",
                "aadhaar_no": m.aadhaar_no or "",
                "current_group": m.assigned_chitti_group.name if m.assigned_chitti_group else "",
            })

        if len(results) < 10:
            users_qs = User.objects.filter(
                Q(email__icontains=query) | Q(username__icontains=query) | Q(first_name__icontains=query)
            ).exclude(id__in=seen_user_ids)[:10]

            for u in users_qs:
                results.append({
                    "id": 0,
                    "user_id": u.id,
                    "name": u.get_full_name() or u.username,
                    "email": u.email or "",
                    "phone": u.username,
                    "address": "",
                    "aadhaar_no": "",
                    "current_group": "",
                })

        return Response({
            "exists": len(results) > 0,
            "results": results
        })


# MEMBER CREATE / ENROL (Group Admin)
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

        phone = data.get("phone") or ""
        email = data.get("email") or ""
        name = data.get("name") or ""
        address = data.get("address") or ""
        aadhaar_no = data.get("aadhaar_no") or ""
        password = data.get("password") or ""
        existing_user_id = request.data.get("existing_user_id")

        user = None
        if existing_user_id:
            try:
                user = User.objects.filter(id=int(existing_user_id)).first()
            except (ValueError, TypeError):
                pass

        if not user and (phone or email):
            user = User.objects.filter(
                Q(username=phone) | Q(email=email) | Q(username=email)
            ).first()

        # Check duplicate inside this group
        if group and user:
            existing_cm = ChittiMember.objects.filter(
                group=group
            ).filter(
                Q(member__user=user) | Q(member__email=email) | Q(member__phone=phone)
            ).exists()
            if existing_cm:
                return Response(
                    {"detail": f"Member is already enrolled in group '{group.name}'"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        if user:
            # Existing User Found -> Find or Create Member profile
            member = Member.objects.filter(user=user).first()
            if not member:
                member = Member.objects.create(
                    user=user,
                    name=name or user.get_full_name() or user.username,
                    email=email or user.email,
                    phone=phone or user.username,
                    address=address,
                    aadhaar_no=aadhaar_no,
                    assigned_chitti_group=group,
                    is_first_login=False
                )
            else:
                if name:
                    member.name = name
                if address:
                    member.address = address
                if aadhaar_no:
                    member.aadhaar_no = aadhaar_no
                if not member.assigned_chitti_group and group:
                    member.assigned_chitti_group = group
                member.save()
        else:
            # Fresh User Registration
            username = phone or email
            if not password:
                password = "".join(random.choices(string.ascii_letters + string.digits, k=8))

            user = User.objects.create_user(
                username=username,
                password=password,
                email=email
            )

            member = Member.objects.create(
                user=user,
                name=name,
                email=email,
                phone=phone,
                address=address,
                aadhaar_no=aadhaar_no,
                assigned_chitti_group=group,
                is_first_login=True
            )

        # 🎟️ Safe Token Creation in ChittiMember
        if group:
            for _ in range(3):
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
                    continue

        return Response({
            "message": "Member enrolled successfully",
            "username": user.username,
            "member_id": member.id,
            "group_id": group.id if group else None,
            "group_name": group.name if group else ""
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
        # CALCULATION
        # -----------------------------
        total_paid = float(sum(p.amount for p in payments))

        # Total subscription amount
        total_amount = duration * monthly_amount

        # Remaining total due
        total_due = max(0, total_amount - total_paid)

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
                "is_advance": (
                    month > current_grp_month
                    and allocated > 0
                )
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
                "total_amount": total_amount,
                "total_paid": total_paid,
                "total_due": total_due,
                "months_paid": sum(
                    1 for m in month_wise
                    if m["status"] == "Paid"
                ),
                "duration_months": duration
            },

            "month_wise_payments": month_wise,

            "recent_transactions": [
                {
                    "amount": p.amount,
                    "paid_date": p.paid_date,
                    "collector": (
                        p.collected_by.user.get_full_name()
                        if p.collected_by
                        else "Admin"
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


def get_member_for_user(request, group_id=None):
    """
    Strictly resolves the Member profile for the currently logged-in user.
    Only returns Member records belonging to THIS user.
    """
    user = request.user
    if not group_id:
        group_id = request.GET.get('group_id') or request.GET.get('group')

    user_filters = Q(user=user)
    if user.email:
        user_filters |= Q(email=user.email)
    if user.username:
        user_filters |= Q(phone=user.username)

    if group_id:
        try:
            gid = int(group_id)
            # 1. Direct group link for this user
            m = Member.objects.filter(user_filters, assigned_chitti_group_id=gid).select_related('assigned_chitti_group').first()
            if m:
                return m
            # 2. Membership link in this group for this user
            cm_filters = Q(member__user=user)
            if user.email:
                cm_filters |= Q(member__email=user.email)
            if user.username:
                cm_filters |= Q(member__phone=user.username)
            cm = ChittiMember.objects.filter(cm_filters, group_id=gid).select_related('member', 'group').first()
            if cm:
                return cm.member
        except (ValueError, TypeError):
            pass

    # Default: first member record belonging to this user
    member = Member.objects.filter(user_filters).select_related('assigned_chitti_group').first()
    if not member:
        cm_filters = Q(member__user=user)
        if user.email:
            cm_filters |= Q(member__email=user.email)
        if user.username:
            cm_filters |= Q(member__phone=user.username)
        cm = ChittiMember.objects.filter(cm_filters).select_related('member', 'group').first()
        if cm:
            member = cm.member

    return member

# -----------------------------
# Member Dashboard
# -----------------------------
class MemberDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_member_for_user(request)
        if not member:
            return Response({
                "member": {"id": 0, "name": request.user.username, "phone": "", "email": request.user.email or ""},
                "total_paid": 0,
                "total_amount": 0,
                "remaining": 0,
                "auctions": [],
                "latest_auction": None,
                "is_winner": False
            })

        payments = Payment.objects.filter(member=member, payment_status="success")
        total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0

        group = member.assigned_chitti_group
        total_amount = getattr(group, 'total_amount', 0) if group else 0
        remaining = max(0, total_amount - total_paid)

        if group:
            auctions = Auction.objects.filter(group=group, winner__isnull=False).order_by('auction_date')
            latest_auction = auctions.last()
            is_winner = auctions.filter(winner__member=member).exists()
        else:
            auctions = Auction.objects.none()
            latest_auction = None
            is_winner = False

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
        member = get_member_for_user(request)
        if not member:
            return Response({
                "id": 0,
                "name": request.user.username,
                "email": request.user.email or "",
                "phone": "",
                "address": "",
                "aadhaar_no": "",
                "assigned_chitti_group_name": "None"
            })
        return Response(MemberSerializer(member).data)


# -----------------------------
# Member Payment History
# -----------------------------
class MemberPaymentsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        member = get_member_for_user(request)
        if not member:
            return Response({
                "group": {"id": 0, "name": "No Active Group", "monthly_amount": 0, "duration": 0, "current_month": 1},
                "summary": {"total_paid": 0, "total_due": 0, "collections_paid": 0},
                "payment_rows": []
            }, status=status.HTTP_200_OK)

        # ✅ Group
        member_record = (
            ChittiMember.objects
            .filter(member=member)
            .select_related('group')
            .first()
        )
        group = member_record.group if member_record else member.assigned_chitti_group

        if not group:
            return Response({
                "group": {"id": 0, "name": "No Active Group", "monthly_amount": 0, "duration": 0, "current_month": 1},
                "summary": {"total_paid": 0, "total_due": 0, "collections_paid": 0},
                "payment_rows": []
            }, status=status.HTTP_200_OK)

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

        monthly_amount = float(group.monthly_amount or 0)
        duration = int(group.duration_months or 1)
        current_grp_month = int(group.current_month or 1)

        total_paid = float(
            payments_qs.aggregate(total=Sum("amount"))["total"] or 0
        )

        payment_rows = []
        payments_list = list(payments_qs)
        overflow_cash = 0.0
        active_payment = None

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

                collector_display = "Admin"
                if active_payment.collected_by:
                    user_obj = active_payment.collected_by.user
                    collector_display = user_obj.get_full_name() or user_obj.username

                month_transactions.append({
                    "amount": take,
                    "date": active_payment.paid_date,
                    "collector": collector_display
                })

                overflow_cash -= take
                target -= take

            if allocated_for_month >= monthly_amount and monthly_amount > 0:
                status_label = "Paid"
            elif allocated_for_month > 0:
                status_label = "Partial"
            else:
                status_label = "Pending"

            payment_rows.append({
                "month": month,
                "target": monthly_amount,
                "paid": allocated_for_month,
                "balance": max(0, monthly_amount - allocated_for_month),
                "status": status_label,
                "transactions": month_transactions,
                "is_advance": month > current_grp_month and allocated_for_month > 0
            })

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
        member = get_member_for_user(request)
        if not member or not member.assigned_chitti_group:
            return Response({
                "member": {"id": 0, "name": request.user.username},
                "group": {"id": 0, "name": "No Active Group"},
                "today": timezone.now().date(),
                "auctions": [],
                "stats": {"total_auctions": 0, "completed_auctions": 0, "pending_auctions": 0}
            }, status=status.HTTP_200_OK)

        group = member.assigned_chitti_group
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
            "auctions": AuctionSerializer(auctions_qs, many=True).data,
            "stats": {
                "total_auctions": auctions_qs.count(),
                "completed_auctions": auctions_qs.filter(winner__isnull=False).count(),
                "pending_auctions": auctions_qs.filter(winner__isnull=True).count(),
            }
        }, status=status.HTTP_200_OK)