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


from datetime import datetime, date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication


class CreateGroupAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        user = request.user

        # 🔒 Block if already created group
        if hasattr(user, 'staffprofile') and user.staffprofile.group:
            return Response(
                {"error": "You already created a group."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            data = request.data

            # =========================
            # 🔥 PLAN
            # =========================
            plan_id = data.get("plan_id")
            if not plan_id:
                raise ValueError("Plan ID missing")

            plan = get_object_or_404(
                SubscriptionPlan,
                id=plan_id,
                is_active=True
            )

            # =========================
            # 🔥 BASIC FIELDS
            # =========================
            name = data.get("name")

            if not hasattr(user, 'staffprofile'):
                raise ValueError("Staff profile missing")

            phone = user.staffprofile.phone
            email = user.email

            monthly_amount = Decimal(str(data.get("monthly_amount", "0")))
            duration_months = int(data.get("duration_months", 0))

            auction_type = data.get("auction_type", "monthly")
            auctions_per_month = int(data.get("auctions_per_month", 1))
            auction_interval_months = data.get("auction_interval_months")

            if auction_type == "interval":
                auction_interval_months = int(auction_interval_months or 0)
                if auction_interval_months <= 0:
                    raise ValueError("Invalid interval months")
            else:
                auction_interval_months = None

            # =========================
            # 📅 DATES
            # =========================
            registration_start = data.get("registration_start_date")
            if not registration_start:
                raise ValueError("Registration date missing")

            registration_date = datetime.strptime(
                registration_start,
                "%Y-%m-%d"
            ).date()

            first_date = data.get("first_auction_date") or data.get("start_date")

            if not first_date:
                raise ValueError("First auction date missing")

            auction_start_date = datetime.strptime(
                first_date,
                "%Y-%m-%d"
            ).date()

            if auction_start_date < registration_date:
                return Response(
                    {"error": "Auction date must be after registration date"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if not name or monthly_amount <= 0 or duration_months <= 0:
                raise ValueError("Invalid basic data")

        except Exception as e:
            return Response(
                {"error": f"Invalid input data: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================
        # 🔥 CREATE GROUP
        # =========================
        group = ChittiGroup.objects.create(
            name=name,
            phone=phone,
            email=email,
            owner=user,
            monthly_amount=monthly_amount,
            duration_months=duration_months,
            total_amount=monthly_amount * duration_months,
            auction_type=auction_type,
            auctions_per_month=auctions_per_month,
            auction_interval_months=auction_interval_months,
            registration_start_date=registration_date,
            start_date=auction_start_date
        )

        # =========================
        # 🔥 FIXED AUCTION CREATION (IMPORTANT)
        # =========================
        base_dates = []
        current_date = auction_start_date

        for month in range(1, duration_months + 1):
            base_dates.append(current_date)
            current_date = current_date + relativedelta(months=1)

        group.create_auctions(base_dates=base_dates)

        # =========================
        # 🔥 UPDATE PROFILE
        # =========================
        profile = user.staffprofile
        profile.group = group
        profile.save()

        # =========================
        # 🔥 SUBSCRIPTION
        # =========================
        subscription = GroupSubscription.objects.create(
            group=group,
            plan=plan
        )
        subscription.activate(start_date=registration_date)

        # =========================
        # ✅ RESPONSE
        # =========================
        return Response({
            "message": "Group created successfully ✅",

            "group": {
                "id": group.id,
                "name": group.name,
                "start_date": str(group.start_date),
                "end_date": str(group.end_date)
            },

            "plan": {
                "id": plan.id,
                "name": plan.name,
                "price": str(plan.price),
                "max_members": plan.max_members,
                "max_groups": plan.max_groups
            },

            "subscription": {
                "is_active": subscription.is_active,
                "start_date": subscription.start_date,
                "end_date": subscription.end_date
            },

            "admin": {
                "name": user.get_full_name() or user.username,
                "email": user.email,
                "phone": user.staffprofile.phone
            }
        }, status=status.HTTP_201_CREATED)
    
    
class GroupAdminProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        profile = get_object_or_404(
            StaffProfile,
            user=user,
            role="group_admin"
        )

        # Groups under this admin
        groups = ChittiGroup.objects.filter(owner=user).annotate(
            members_count=Count("chitti_members")
        )

        groups_count = groups.count()
        total_members_count = sum(g.members_count for g in groups)

        # Main group for subscription
        main_group = groups.filter(parent_group__isnull=True).first()

        effective_sub = None
        subscription_status = {
            "active": False,
            "days_left": 0,
            "hours_left": 0
        }
        time_left = "0"

        max_groups = 0
        max_members = 0

        if main_group:
            effective_sub = get_effective_subscription(main_group)

        if effective_sub:
            subscription_status = get_subscription_status(effective_sub)
            time_left = get_time_left(effective_sub)

            max_groups = effective_sub.plan.max_groups
            max_members = effective_sub.plan.max_members

        # Remaining calculations (avoid negative values)
        remaining_groups = max(max_groups - groups_count, 0)
        remaining_members = max(max_members - total_members_count, 0)

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
                "remaining_members": remaining_members,
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

        # 🔐 Role check
        if not hasattr(user, "staffprofile") or user.staffprofile.role != "group_admin":
            return Response(
                {"error": "Only group admin allowed"},
                status=status.HTTP_403_FORBIDDEN
            )

        # ================= BASE QUERYSETS =================
        groups = ChittiGroup.objects.filter(owner=user)
        payments = Payment.objects.filter(
            group__owner=user,
            payment_status="success"
        )

        # ================= GROUPS =================
        total_groups = groups.count()
        active_groups = groups.filter(is_active=True).count()

        # ================= MEMBERS =================
        total_members = ChittiMember.objects.filter(
            group__owner=user
        ).count()

        # ================= THIS MONTH COLLECTION =================
        month_start = today.replace(day=1)

        this_month_collection = payments.filter(
            received_by_admin=True,   # ✅ IMPORTANT FIX
            paid_date__gte=month_start
        ).aggregate(total=Sum("amount"))["total"] or 0

        # ================= TOTAL RECEIVED =================
        total_received = payments.filter(
            received_by_admin=True   # ✅ IMPORTANT FIX
        ).aggregate(total=Sum("amount"))["total"] or 0

        # ================= EXTRA (BONUS) =================
        pending_admin_approval = payments.filter(
            received_by_admin=False
        ).aggregate(total=Sum("amount"))["total"] or 0

        total_expected = groups.aggregate(
            total=Sum("total_amount")
        )["total"] or 0

        collection_percentage = 0
        if total_expected > 0:
            collection_percentage = round((total_received / total_expected) * 100, 2)

        # ================= RESPONSE =================
        data = {
            "stats": {
                "total_groups": total_groups,
                "active_groups": active_groups,
                "total_members": total_members,
                "this_month_collection": float(this_month_collection),
                "total_received": float(total_received),

                # 🔥 BONUS
                "pending_admin_approval": float(pending_admin_approval),
                "total_expected": float(total_expected),
                "collection_percentage": collection_percentage,
            },
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "code": g.code,
                    "is_active": g.is_active,
                    "total_members": g.total_members,
                    "monthly_amount": float(g.monthly_amount),
                    "duration_months": g.duration_months,
                    "total_amount": float(g.total_amount),

                    "start_date": g.start_date.strftime("%Y-%m-%d") if g.start_date else None,

                    "collector_name": (
                        g.collector.user.username
                        if g.collector and hasattr(g.collector, "user")
                        else "Not Assigned"
                    ),
                }
                for g in groups
            ]
        }

        return Response(data, status=status.HTTP_200_OK)

# ==================================================
# ADMIN GROUP LIST API
# main group + its child groups (ONLY created by this admin)
class AdminGroupListAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # 🔍 Fetch groups (same as template)
        groups = ChittiGroup.objects.filter(
            owner=user
        ).prefetch_related('auctions')

        # ❌ No groups → same as redirect
        if not groups.exists():
            return Response({
                "redirect": "create_group",
                "message": "No groups found"
            }, status=404)

        result = []

        for group in groups:

            # ✅ BASE START (same)
            base_start = group.registration_start_date or group.start_date

            # ✅ END DATE (FIXED SAME AS TEMPLATE)
            end_date = None
            if base_start and group.duration_months:
                end_date = base_start + relativedelta(
                    months=group.duration_months
                ) - relativedelta(days=1)   # 🔥 IMPORTANT FIX

            # ✅ EXPIRED CHECK (same)
            is_expired = end_date and date.today() > end_date

            # ✅ FIRST AUCTION (MISSING IN YOUR API)
            first_auction = group.auctions.all().order_by('auction_date').first()
            first_auction_date = first_auction.auction_date if first_auction else None

            # ✅ DAYS LEFT (FIXED SAME LOGIC)
            days_until_first_auction = None
            if group.start_date:
                days_until_first_auction = (group.start_date - date.today()).days

            # ✅ BUILD RESPONSE (DON'T MUTATE OBJECT)
            result.append({
                "id": group.id,
                "name": group.name,
                "monthly_amount": group.monthly_amount,
                "duration_months": group.duration_months,
                "total_amount": group.total_amount,

                "start_date": group.start_date,
                "registration_start_date": group.registration_start_date,

                # 🔥 computed fields (same as template)
                "end_date": end_date,
                "is_expired": is_expired,
                "first_auction_date": first_auction_date,
                "days_until_first_auction": days_until_first_auction
            })

        return Response({
            "groups": result
        }, status=200)
    
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

        try:
            # =========================
            # 📥 INPUTS (SAFE)
            # =========================
            name = request.data.get("name", "").strip()

            monthly_amount = Decimal(request.data.get("monthly_amount") or 0)
            duration_months = int(request.data.get("duration_months") or 0)

            auctions_per_month = int(request.data.get("auctions_per_month") or 1)
            auction_type = request.data.get("auction_type", "monthly")
            auction_interval_months = request.data.get("auction_interval_months")

            # =========================
            # 🔁 INTERVAL VALIDATION
            # =========================
            if auction_type == "interval":
                auction_interval_months = int(auction_interval_months or 0)
                if auction_interval_months <= 0:
                    raise ValueError("Invalid interval")
            else:
                auction_interval_months = None

            # =========================
            # 📅 START DATE
            # =========================
            date_input = request.data.get("start_date")

            if not date_input:
                raise ValueError("start_date required")

            try:
                start_date = datetime.strptime(date_input, "%d-%m-%Y").date()
            except ValueError:
                start_date = datetime.strptime(date_input, "%Y-%m-%d").date()

            # =========================
            # 🔥 AUCTION DATES VALIDATION
            # =========================
            base_dates = []

            for i in range(1, auctions_per_month + 1):
                d = request.data.get(f"auction_date_{i}")

                if not d:
                    raise ValueError("All auction dates required")

                auction_date = datetime.strptime(d, "%Y-%m-%d").date()

                if auction_date < start_date:
                    return Response(
                        {"error": f"Auction date {i} must be after start date"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                base_dates.append(auction_date)

            # ❌ Duplicate check
            if len(base_dates) != len(set(base_dates)):
                return Response(
                    {"error": "Duplicate auction dates not allowed"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ❌ Order check
            if base_dates != sorted(base_dates):
                return Response(
                    {"error": "Auction dates must be in ascending order"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # =========================
            # BASIC VALIDATION
            # =========================
            if not name or monthly_amount <= 0 or duration_months <= 0:
                return Response(
                    {"error": "Invalid input"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        total_amount = monthly_amount * duration_months

        # 🔍 MAIN GROUP
        main_group = ChittiGroup.objects.filter(
            owner=user,
            parent_group__isnull=True
        ).first()

        # =============================
        # 🔧 CREATE FUNCTION
        # =============================
        def create_group(parent=None):

            group = ChittiGroup.objects.create(
                owner=user,
                parent_group=parent,
                name=name,
                monthly_amount=monthly_amount,
                duration_months=duration_months,
                total_amount=total_amount,

                auction_type=auction_type,
                auctions_per_month=auctions_per_month,
                auction_interval_months=auction_interval_months,

                registration_start_date=start_date,
                start_date=start_date
            )

            # 🔥 SAFE CALL (IMPORTANT FIX)
            if hasattr(group, "create_auctions"):
                group.create_auctions(base_dates=base_dates)
            else:
                raise Exception("create_auctions method missing in model")

            return group

        # =============================
        # 🟢 MAIN GROUP
        # =============================
        if not main_group:
            group = create_group()

            profile = user.staffprofile
            profile.group = group
            profile.save()

            return Response({
                "message": "Main group created successfully",
                "group": ChittiGroupSerializer(group).data
            }, status=status.HTTP_201_CREATED)

        # =============================
        # 🔵 SUB GROUP
        # =============================
        subscription = get_effective_subscription(main_group)

        if not subscription:
            return Response(
                {"error": "No active subscription"},
                status=status.HTTP_403_FORBIDDEN
            )

        if not can_create_group(user):
            return Response(
                {"error": f"Limit reached for {subscription.plan.name}"},
                status=status.HTTP_403_FORBIDDEN
            )

        group = create_group(parent=main_group)

        return Response({
            "message": "Sub group created successfully",
            "group": ChittiGroupSerializer(group).data
        }, status=status.HTTP_201_CREATED)

# ==================================================
# ==================================================
# VIEW GROUP DETAILS API
# ==================================================

from dateutil.relativedelta import relativedelta


class GroupDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):

        # 1️⃣ Fetch Group
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 2️⃣ Members & Auctions
        members = group.chitti_members.select_related("member").all()
        total_members = members.count()

        auctions = group.auctions.select_related('winner').all().order_by('month_no', 'auction_no')

        # 3️⃣ Financial Tracking
        payments = Payment.objects.filter(
            group=group,
            payment_status='success'
        )

        total_collected = payments.filter(
            received_by_admin=True
        ).aggregate(total=Sum('amount'))['total'] or 0

        pending_total = payments.filter(
            received_by_admin=False
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 4️⃣ Pot Logic
        monthly_pot = group.monthly_amount * total_members

        # 5️⃣ Progress Tracking
        completed_auctions = auctions.filter(winner__isnull=False)
        completed_count = completed_auctions.count()

        completed_months = completed_auctions.values('month_no').distinct().count()

        current_month = completed_months + 1
        remaining_months = max(0, (group.duration_months or 0) - completed_months)

        # 6️⃣ Prize Calculation
        auction_list = []
        for auction in auctions:
            discount = auction.bid_amount or 0
            prize = monthly_pot - discount

            auction_list.append({
                "id": auction.id,
                "month_no": auction.month_no,
                "auction_no": auction.auction_no,
                "auction_date": auction.auction_date,
                "winner": auction.winner.member.name if auction.winner else None,
                "bid_amount": auction.bid_amount,
                "prize": prize
            })

        # 7️⃣ Last Auction
        last_auction = completed_auctions.order_by('auction_date').last()

        last_winner = last_auction.winner.member.name if last_auction and last_auction.winner else None
        last_discount = last_auction.bid_amount if last_auction else 0
        last_prize = (monthly_pot - last_discount) if last_auction else 0

        # 8️⃣ Date Logic
        base_date = group.registration_start_date or group.start_date

        end_date = None
        is_expired = False

        if base_date and group.duration_months:
            end_date = base_date + relativedelta(
                months=group.duration_months
            ) - relativedelta(days=1)

            is_expired = date.today() > end_date

        # 9️⃣ Efficiency
        expected_total = group.monthly_amount * total_members * completed_months

        efficiency = 0
        if expected_total > 0:
            efficiency = (total_collected / expected_total) * 100

        # 🔟 FINAL RESPONSE
        return Response({

            # 🔹 GROUP
            "group": {
                "id": group.id,
                "name": group.name,
                "monthly_amount": group.monthly_amount,
                "duration_months": group.duration_months,
                "total_amount": group.total_amount,
                "start_date": group.start_date,
                "registration_start_date": group.registration_start_date,

                "end_date": end_date,
                "is_expired": is_expired,

                # 🔥 extra
                "total_members": total_members,
                "monthly_pot": monthly_pot,
                "current_month": current_month,
                "completed_months": completed_months,
                "remaining_months": remaining_months,

                "total_collected": total_collected,
                "pending_total": pending_total,
                "collection_efficiency": round(efficiency, 1),

                "last_winner": last_winner,
                "last_prize": last_prize,
                "last_discount": last_discount
            },

            # 🔹 MEMBERS
            "members": [
                {
                    "id": cm.id,
                    "name": cm.member.name,
                    "phone": cm.member.phone,
                    "token_no": cm.token_no,
                    "status": cm.member_status
                }
                for cm in members
            ],

            # 🔹 AUCTIONS (FULL DATA)
            "auctions": auction_list,

            # 🔹 TODAY (for frontend badge logic)
            "today": date.today()
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
# 1️⃣ Auction List API
# ==================================================
class AuctionListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        groups = ChittiGroup.objects.filter(owner=request.user).order_by("-id")

        data = [
            {
                "id": g.id,
                "name": g.name,
                "duration_months": g.duration_months,
                "start_date": g.start_date,
                "end_date": g.start_date + relativedelta(months=g.duration_months)
            }
            for g in groups
        ]

        return Response({"groups": data})


# ==================================================
# 2️⃣ Auction List Group API (FIXED)
# ==================================================
class AuctionListGroupAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        months = []

        for i in range(1, group.duration_months + 1):

            month_auctions = group.auctions.filter(
                month_no=i
            ).order_by("auction_no")

            months.append({
                "month_no": i,
                "auctions": [
                    {
                        "id": a.id,
                        "auction_date": a.auction_date,
                        "auction_no": a.auction_no,
                        "is_closed": a.is_closed,
                        "winner": a.winner.member.name if a.winner else None
                    }
                    for a in month_auctions
                ]
            })

        return Response({
            "group": {
                "id": group.id,
                "name": group.name,
                "duration_months": group.duration_months,
                "start_date": group.start_date,
                "end_date": group.start_date + relativedelta(months=group.duration_months)
            },
            "months": months
        })


# ==================================================
# 3️⃣ Add Auction API (FULL FIXED)
# ==================================================
class AddAuctionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        group_id = request.data.get("group_id")
        auction_date_str = request.data.get("auction_date")

        if not group_id or not auction_date_str:
            return Response(
                {"error": "group_id and auction_date required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            auction_date = datetime.strptime(
                auction_date_str, "%d/%m/%Y"
            ).date()
        except ValueError:
            return Response(
                {"error": "Use DD/MM/YYYY format"},
                status=status.HTTP_400_BAD_REQUEST
            )

        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        # 🔹 Duration check
        end_date = group.start_date + relativedelta(
            months=group.duration_months
        )

        if auction_date < group.start_date or auction_date >= end_date:
            return Response(
                {"error": "Date outside group duration"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔥 Month calculation (same as web)
        month_no = (
            (auction_date.year - group.start_date.year) * 12
            + (auction_date.month - group.start_date.month)
            + 1
        )

        # 🔹 Monthly limit
        monthly_count = group.auctions.filter(
            month_no=month_no
        ).count()

        if monthly_count >= group.auctions_per_month:
            return Response(
                {"error": f"Max {group.auctions_per_month} auctions allowed in this month"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔹 Total limit
        total = group.auctions.count()

        if total >= group.total_auctions:
            return Response(
                {"error": "Total auction limit reached"},
                status=status.HTTP_400_BAD_REQUEST
            )

        auction_no = monthly_count + 1

        auction = Auction.objects.create(
            group=group,
            auction_date=auction_date,
            month_no=month_no,
            auction_no=auction_no
        )

        return Response({
            "message": "Auction created",
            "month_no": month_no,
            "auction_no": auction_no
        }, status=status.HTTP_201_CREATED)


# ==================================================
# 4️⃣ Auction Spin API
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
            return Response({"error": "Auction completed"}, status=400)

        all_members = ChittiMember.objects.filter(group=auction.group)

        previous_winners = auction.group.auctions.exclude(
            winner__isnull=True
        ).values_list("winner_id", flat=True)

        eligible = all_members.exclude(id__in=previous_winners)

        if not eligible.exists():
            return Response({"error": "No members left"}, status=400)

        return Response({
            "auction_id": auction.id,
            "eligible_members": [
                {"id": m.id, "name": m.member.name}
                for m in eligible
            ]
        })


# ==================================================
# 5️⃣ Assign Winner API (FIXED)
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
            return Response({"error": "Already closed"}, status=400)

        # 🔥 DATE VALIDATION (same as web)
        if auction.auction_date != date.today():
            return Response(
                {"error": "Spin allowed only on auction date"},
                status=400
            )

        members = ChittiMember.objects.filter(group=auction.group)

        previous = auction.group.auctions.exclude(
            winner__isnull=True
        ).values_list("winner_id", flat=True)

        eligible = members.exclude(id__in=previous)

        if not eligible.exists():
            return Response({"error": "No eligible members"}, status=400)

        winner = random.choice(list(eligible))

        auction.assign_winner(winner, bid_amount=0)

        return Response({
            "message": "Winner assigned",
            "winner": {
                "id": winner.id,
                "name": winner.member.name
            }
        })


# ==================================================
# 6️⃣ Auction Detail API
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
    


class AssignAllWinnersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, auction_id):

        initial_auction = get_object_or_404(
            Auction.objects.select_related('group'),
            id=auction_id,
            group__owner=request.user
        )

        group = initial_auction.group
        winners_list = request.data.get("winners", [])

        if not winners_list:
            return Response({"error": "No winner data received"}, status=400)

        try:
            # 🔥 Already winners (global)
            existing_winners = set(
                Auction.objects.filter(
                    group=group,
                    winner__isnull=False
                ).values_list('winner_id', flat=True)
            )

            # 🔥 Last completed month
            last_month = Auction.objects.filter(
                group=group,
                winner__isnull=False
            ).aggregate(Max('month_no'))['month_no__max'] or 0

            for item in winners_list:
                month_no = int(item.get("month"))
                member_id = item.get("id")

                # ❌ Restrict past months
                if month_no <= last_month:
                    return Response({
                        "error": f"You can only add winners after month {last_month}"
                    }, status=400)

                # ❌ Already winner check (global)
                if member_id in existing_winners:
                    return Response({
                        "error": f"Member {member_id} already won"
                    }, status=400)

                winner_member = ChittiMember.objects.get(
                    id=member_id,
                    group=group
                )

                # 🔥 Get all auctions in that month
                monthly_auctions = group.auctions.filter(
                    month_no=month_no
                ).order_by("auction_no")

                # ❌ Same month duplicate check
                if monthly_auctions.filter(winner=winner_member).exists():
                    return Response({
                        "error": f"Member already selected in month {month_no}"
                    }, status=400)

                # 🔥 Decide auction slot
                if monthly_auctions.exists():
                    next_auction_no = monthly_auctions.count() + 1
                else:
                    next_auction_no = 1

                # 🔥 Create auction always (multi-slot support)
                auction_date = group.start_date + relativedelta(months=month_no - 1)

                auction = Auction.objects.create(
                    group=group,
                    month_no=month_no,
                    auction_no=next_auction_no,
                    auction_date=auction_date,
                    selection_type="manual"
                )

                # 🔥 Assign winner
                auction.assign_winner(winner_member, bid_amount=0)

                # 🔥 Add to used list
                existing_winners.add(member_id)

            return Response({"success": True})

        except ChittiMember.DoesNotExist:
            return Response({"error": "Member not found"}, status=404)

        except ValueError as e:
            return Response({"error": str(e)}, status=400)

        except Exception as e:
            return Response({"error": f"Unexpected error: {str(e)}"}, status=500)


class EditAuctionDatesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):

        group = get_object_or_404(
            ChittiGroup,
            id=group_id,
            owner=request.user
        )

        auction_id = request.data.get("auction_id")
        month_no = request.data.get("month_no")
        new_date_str = request.data.get("new_date")

        if not new_date_str:
            return Response({"error": "Valid date required"}, status=400)

        try:
            new_date = datetime.strptime(new_date_str, "%d/%m/%Y").date()
        except ValueError:
            return Response({"error": "Use DD/MM/YYYY format"}, status=400)

        try:
            # =========================
            # UPDATE EXISTING
            # =========================
            if auction_id:
                auction = get_object_or_404(
                    Auction,
                    id=auction_id,
                    group=group
                )

                if auction.winner:
                    return Response(
                        {"error": "Cannot edit completed auction"},
                        status=400
                    )

                auction.auction_date = new_date
                auction.save()

                return Response({
                    "message": f"Month {auction.month_no} updated"
                })

            # =========================
            # CREATE NEW
            # =========================
            elif month_no:

                if group.auctions.filter(month_no=month_no).exists():
                    return Response(
                        {"error": f"Month {month_no} already exists"},
                        status=400
                    )

                Auction.objects.create(
                    group=group,
                    month_no=month_no,
                    auction_no=1,
                    auction_date=new_date
                )

                return Response({
                    "message": f"Auction created for month {month_no}"
                })

            else:
                return Response({"error": "Invalid request"}, status=400)

        except Exception as e:
            return Response(
                {"error": f"Unexpected error: {str(e)}"},
                status=500
            )