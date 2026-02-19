# chitti/api/v1/views.py

from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import count
from django.utils import timezone
from django.db.models import Count
from dateutil.relativedelta import relativedelta
from django.shortcuts import get_object_or_404
from django.db import IntegrityError, transaction
from django.db.models import Sum
from datetime import date
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.contrib.auth.models import User
import random
from accounts.models import StaffProfile
from chitti.models import Auction, ChittiGroup, ChittiMember
from payments.models import Payment
from subscriptions.models import GroupSubscription, SubscriptionPlan
from subscriptions.utils import (
    get_effective_subscription,
    can_create_group,
    get_subscription_status,
    get_time_left
)

from .serializers import (
    CashCollectorCreateSerializer,
    CashCollectorListSerializer,
    CashCollectorUpdateSerializer,
    ChittiGroupSerializer,
    AuctionSerializer
)


from django.db.models import Count

class GroupAdminProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        profile = get_object_or_404(
            StaffProfile,
            user=user,
            role='group_admin'
        )

        # Groups under this admin
        groups = ChittiGroup.objects.filter(owner=user).annotate(
            members_count=Count('chitti_members')
        )

        groups_count = groups.count()
        total_members_count = sum(g.members_count for g in groups)

        # Main group (for subscription)
        main_group = groups.filter(parent_group__isnull=True).first()

        effective_sub = get_effective_subscription(main_group) if main_group else None
        subscription_status = get_subscription_status(effective_sub) if effective_sub else None
        time_left = get_time_left(effective_sub) if effective_sub else "0"

        # 🔹 Max/Remaining groups
        max_groups = effective_sub.plan.max_groups if effective_sub else None
        remaining_groups = max_groups - groups_count if max_groups is not None else None

        # 🔹 Max/Remaining members (total across all groups)
        max_members = effective_sub.plan.max_members if effective_sub else None
        remaining_members = max_members - total_members_count if max_members is not None else None

        data = {
            "profile": {
                "id": profile.id,
                "name": user.get_full_name() or user.username,
                "email": user.email,
                "phone": profile.phone,
                "role": profile.role,
            },
            "groups_count": groups_count,
            "members_count": total_members_count,
            "effective_subscription": {
                "plan": effective_sub.plan.name if effective_sub else None,
                "is_active": effective_sub.is_active if effective_sub else False,
                "max_groups": max_groups,
                "remaining_groups": remaining_groups,
                "max_members": max_members,
                "remaining_members": remaining_members
            },
            "subscription_status": subscription_status,
            "time_left": time_left
        }

        return Response(data)




class GroupAdminDashboardAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        today = timezone.now().date()

        # 🔐 role check (same as @group_admin_required)
        if not hasattr(user, "staffprofile") or user.staffprofile.role != "group_admin":
            return Response(
                {"error": "Only group admin allowed"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ================= GROUPS =================
        groups = ChittiGroup.objects.filter(owner=user)
        total_groups = groups.count()
        active_groups = groups.filter(is_active=True).count()

        # ================= MEMBERS =================
        total_members = ChittiMember.objects.filter(
            group__owner=user
        ).count()

        # ================= THIS MONTH COLLECTION =================
        month_start = today.replace(day=1)

        this_month_collection = Payment.objects.filter(
            group__owner=user,
            payment_status="success",
            paid_date__gte=month_start
        ).aggregate(total=Sum("amount"))["total"] or 0

        # ================= TOTAL COLLECTION =================
        total_received = Payment.objects.filter(
            group__owner=user,
            payment_status="success"
        ).aggregate(total=Sum("amount"))["total"] or 0

        # ================= RESPONSE =================
        return Response({
            "stats": {
                "total_groups": total_groups,
                "active_groups": active_groups,
                "total_members": total_members,
                "this_month_collection": this_month_collection,
                "total_received": total_received,
            },
 "groups": [
            {
                "id": g.id,
                "name": g.name,
                "code": g.code,
                "is_active": g.is_active,
                "total_members": g.total_members,
                "monthly_amount": g.monthly_amount,
                "duration_months": g.duration_months,
                "start_date": g.start_date,  
            }
    for g in groups
]
        }, status=status.HTTP_200_OK)
    

# ==================================================
# ADMIN GROUP LIST API
# main group + its child groups (ONLY created by this admin)
# ==================================================
class AdminGroupListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        user = request.user

        # Fetch groups created by this admin
        groups = ChittiGroup.objects.filter(owner=user).order_by('parent_group_id', 'id')

        # Calculate end_date_calculated and is_expired for each group
        for group in groups:
            if group.start_date and group.duration_months:
                group.end_date_calculated = group.start_date + relativedelta(months=group.duration_months)
            else:
                group.end_date_calculated = None  # Unlimited

            # Expired check
            if group.end_date_calculated and date.today() > group.end_date_calculated:
                group.is_expired = True
            else:
                group.is_expired = False

        serializer = ChittiGroupSerializer(groups, many=True)

        return Response({
            "count": groups.count(),
            "groups": serializer.data
        })
    
class AdminGroupCreateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):

        user = request.user

        # 🔐 ROLE CHECK
        if not hasattr(user, "staffprofile") or user.staffprofile.role != "group_admin":
            return Response(
                {"error": "Only group admins can create groups"},
                status=status.HTTP_403_FORBIDDEN
            )

        # 🔎 INPUT VALIDATION
        try:
            name = request.data.get("name", "").strip()
            monthly_amount = Decimal(str(request.data.get("monthly_amount")))
            duration_months = int(request.data.get("duration_months"))

            date_input = request.data.get("start_date")

            try:
                start_date = datetime.strptime(date_input, "%d-%m-%Y").date()
            except ValueError:
                start_date = datetime.strptime(date_input, "%Y-%m-%d").date()

            if not name or monthly_amount <= 0 or duration_months <= 0:
                raise ValueError

        except (ValueError, TypeError, InvalidOperation):
            return Response(
                {"error": "Invalid input data"},
                status=status.HTTP_400_BAD_REQUEST
            )

        total_amount = monthly_amount * duration_months

        # 🔍 CHECK MAIN GROUP
        main_group = ChittiGroup.objects.filter(
            owner=user,
            parent_group__isnull=True
        ).first()

        # ==================================================
        # CREATE MAIN GROUP
        # ==================================================
        if not main_group:

            main_group = ChittiGroup.objects.create(
                owner=user,
                name=name,
                monthly_amount=monthly_amount,
                duration_months=duration_months,
                total_amount=total_amount,
                start_date=start_date
            )

            return Response({
                "message": "Main group created successfully",
                "group": ChittiGroupSerializer(main_group).data
            }, status=status.HTTP_201_CREATED)

        # ==================================================
        # CREATE CHILD GROUP
        # ==================================================
        subscription = get_effective_subscription(main_group)

        if not subscription:
            return Response(
                {"error": "No active subscription"},
                status=status.HTTP_403_FORBIDDEN
            )

        if not can_create_group(user):
            return Response(
                {"error": "Group limit reached"},
                status=status.HTTP_403_FORBIDDEN
            )

        child_group = ChittiGroup.objects.create(
            owner=user,
            parent_group=main_group,
            name=name,
            monthly_amount=monthly_amount,
            duration_months=duration_months,
            total_amount=total_amount,
            start_date=start_date
        )

        return Response({
            "message": "Child group created successfully",
            "group": ChittiGroupSerializer(child_group).data
        }, status=status.HTTP_201_CREATED)


# ==================================================
# ==================================================
# VIEW GROUP DETAILS API
# ==================================================
# ==================================================
# VIEW GROUP DETAILS API (KURI BASED)
# ==================================================
from datetime import date
from dateutil.relativedelta import relativedelta

class GroupDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 🔹 Calculate end date (start_date + duration_months)
        if group.start_date and group.duration_months:
            end_date_calculated = group.start_date + relativedelta(
                months=group.duration_months
            )
        else:
            end_date_calculated = None  # Unlimited

        # 🔹 Expired check
        if end_date_calculated and date.today() > end_date_calculated:
            is_expired = True
        else:
            is_expired = False

        return Response({

            # 🔹 Group basic details
            "group": {
                "id": group.id,
                "name": group.name,
                "monthly_amount": group.monthly_amount,
                "duration_months": group.duration_months,
                "total_amount": group.total_amount,
                "start_date": group.start_date,
                "end_date_calculated": end_date_calculated,
                "is_expired": is_expired
            },

            # 🔹 Members
            "members": [
                {
                    "id": cm.id,
                    "name": cm.member.name,
                    "phone": cm.member.phone,
                    "token_no": cm.token_no,
                    "status": cm.member_status
                }
                for cm in group.chitti_members.select_related("member")
            ],

            # 🔹 Auctions
            "auctions": AuctionSerializer(
                group.auctions.all(),
                many=True
            ).data
        })


class EditGroupAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, group_id):
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        serializer = ChittiGroupSerializer(
            group,
            data=request.data,
            partial=True   # allow partial update
        )

        if serializer.is_valid():
            serializer.save()
            return Response({
                "message": "Group updated successfully",
                "total_amount": serializer.data["total_amount"]
            })

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CashCollectorCreateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = CashCollectorCreateSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        username = data["username"]
        email = data["email"]
        group = data.get("group")

        # ✅ Group Required
        if not group:
            return Response(
                {"error": "Group is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Ensure group belongs to logged-in admin
        if group.owner != request.user:
            return Response(
                {"error": "You can only assign collectors to your own groups"},
                status=status.HTTP_403_FORBIDDEN
            )

        # 🔥 NEW CHECK: Already has collector?
        if group.collector:
            return Response(
                {
                    "error": f"Collector already assigned to group '{group.name}'"
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Username exists
        if User.objects.filter(username=username).exists():
            return Response(
                {"error": "Username already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Email exists
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already exists"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=data["password"]
            )

            collector = StaffProfile.objects.create(
                user=user,
                phone=data["phone"],
                role="collector"
            )

            group.collector = collector
            group.save()

        except IntegrityError:
            return Response(
                {"error": "User creation failed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "message": "Cash collector created successfully",
                "collector_id": collector.id,
                "group": group.name,
            },
            status=status.HTTP_201_CREATED
        )

    
# LIST CASH COLLECTORS (Group Admin)
class CashCollectorListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = ChittiGroup.objects.filter(owner=request.user)

        collectors = StaffProfile.objects.filter(
            role="collector",
            assigned_chitti_groups__in=groups
        ).select_related("user").distinct()

        return Response({
            "count": collectors.count(),
            "results": CashCollectorListSerializer(collectors, many=True).data
        })



# UPDATE CASH COLLECTOR
class CashCollectorUpdateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        collector = get_object_or_404(
            StaffProfile,
            pk=pk,
            role="collector",
            assigned_chitti_groups__owner=request.user
        )

        serializer = CashCollectorUpdateSerializer(
            collector,
            data=request.data,
            partial=True,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({"message": "Cash collector updated"})



class CashCollectorDeleteAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        collector = get_object_or_404(
            StaffProfile,
            pk=pk,
            role="collector",
            assigned_chitti_groups__owner=request.user
        )

        username = collector.user.username
        collector.user.delete()

        return Response(
            {"message": f"Cash collector '{username}' deleted"},
            status=status.HTTP_200_OK
        )



# ==================================================
# 5️⃣ Auction List API
# ==================================================
class AuctionListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get all groups for the logged-in user
        groups = ChittiGroup.objects.filter(owner=request.user)

        # Serialize the data manually
        group_data = []
        for group in groups:
            group_data.append({
                "id": group.id,
                "name": group.name,
                "duration_months": group.duration_months,
                "start_date": group.start_date,
                "end_date": group.start_date + relativedelta(months=group.duration_months)
            })

        return Response({
            "groups": group_data
        })
    


class AuctionListGroupAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # Prepare months and auctions
        auctions_sorted = group.auctions.all().order_by('auction_date')
        months = []
        for i in range(1, group.duration_months + 1):
            auction = auctions_sorted[i-1] if i-1 < len(auctions_sorted) else None
            months.append({
                'month_no': i,
                'auction': {
                    'id': auction.id,
                    'auction_date': auction.auction_date,
                    'is_closed': auction.is_closed,
                    'winner': auction.winner.member.name if auction and auction.winner else None
                } if auction else None
            })

        return Response({
            'group': {
                'id': group.id,
                'name': group.name,
                'duration_months': group.duration_months,
                'start_date': group.start_date,
                'end_date': group.start_date + relativedelta(months=group.duration_months)
            },
            'months': months
        })


# ==================================================
# 1️⃣ Add Auction API
# ==================================================
class AddAuctionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group_id = request.data.get("group_id")
        auction_date_str = request.data.get("auction_date")

        if not group_id or not auction_date_str:
            return Response(
                {"error": "group_id and auction_date are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Convert date (DD/MM/YYYY)
        try:
            auction_date = datetime.strptime(
                auction_date_str, "%d/%m/%Y"
            ).date()
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use DD/MM/YYYY"},
                status=status.HTTP_400_BAD_REQUEST
            )

        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 🔹 1️⃣ Check auction date within group duration period
        group_end_date = group.start_date + relativedelta(
            months=group.duration_months
        )

        if auction_date < group.start_date or auction_date >= group_end_date:
            return Response(
                {"error": "Auction date exceeds group duration period."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔹 2️⃣ Same month duplicate check
        month_exists = group.auctions.filter(
            auction_date__year=auction_date.year,
            auction_date__month=auction_date.month
        ).exists()

        if month_exists:
            return Response(
                {"error": "An auction already exists for this month."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔹 3️⃣ Duration auction count check
        total_auctions = group.auctions.count()
        if total_auctions >= group.duration_months:
            return Response(
                {"error": "Auction limit reached for this group."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔹 4️⃣ Calculate next month_no automatically
        next_month_no = total_auctions + 1

        # Create auction
        auction = Auction.objects.create(
            group=group,
            auction_date=auction_date,
            month_no=next_month_no
        )

        return Response(
            {
                "message": "Auction created successfully",
                "auction_number": next_month_no,
                "auction_date": auction_date.strftime("%d/%m/%Y")
            },
            status=status.HTTP_201_CREATED
        )

# ==================================================
# 2️⃣ Auction Spin API (Eligible Members)
# ==================================================
class AuctionSpinAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, auction_id):

        auction = get_object_or_404(
            Auction,
            id=auction_id,
            group__owner=request.user
        )

        if auction.is_closed:
            return Response(
                {"error": "Auction already completed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        all_members = ChittiMember.objects.filter(
            group=auction.group
        )

        previous_winners = auction.group.auctions.exclude(
            winner__isnull=True
        ).values_list("winner_id", flat=True)

        eligible_members = all_members.exclude(
            id__in=previous_winners
        )

        if not eligible_members.exists():
            return Response(
                {"error": "No eligible members left"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "auction_id": auction.id,
            "group": auction.group.name,
            "eligible_members": [
                {
                    "id": m.id,
                    "name": m.member.name
                }
                for m in eligible_members
            ]
        })


# ==================================================
# 3️⃣ Assign Winner API
# ==================================================
class AssignWinnerAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, auction_id):

        auction = get_object_or_404(
            Auction,
            id=auction_id,
            group__owner=request.user
        )

        if auction.is_closed:
            return Response(
                {"error": "Auction already closed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        all_members = ChittiMember.objects.filter(
            group=auction.group
        )

        previous_winners = auction.group.auctions.exclude(
            winner__isnull=True
        ).values_list("winner_id", flat=True)

        eligible_members = all_members.exclude(
            id__in=previous_winners
        )

        if not eligible_members.exists():
            return Response(
                {"error": "No eligible members left"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🎯 Random winner selection
        winner = random.choice(list(eligible_members))

        # Assign winner (your model method)
        auction.assign_winner(winner, bid_amount=0)

        return Response({
            "message": "Winner assigned successfully",
            "winner": {
                "id": winner.id,
                "name": winner.member.name
            }
        })


# ==================================================
# 4️⃣ Auction Detail API
# ==================================================
class AuctionDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, auction_id):

        auction = get_object_or_404(
            Auction.objects.select_related(
                "group", "winner", "winner__member"
            ),
            id=auction_id,
            group__owner=request.user
        )

        return Response({
            "id": auction.id,
            "group": auction.group.name,
            "auction_date": auction.auction_date,
            "is_closed": auction.is_closed,
            "winner": {
                "id": auction.winner.id,
                "name": auction.winner.member.name
            } if auction.winner else None
        })