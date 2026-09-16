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


def get_collector_groups(staff, group_id=None):
    if group_id:
        try:
            gid = int(group_id)
            matched = ChittiGroup.objects.filter(id=gid, is_active=True)
            if matched.exists():
                return matched
        except (ValueError, TypeError):
            pass

    if staff.role == 'collector':
        # 1. Assigned Kuris via collector FK on ChittiGroup
        assigned = staff.assigned_chitti_groups.filter(is_active=True)
        if assigned.exists():
            return assigned.distinct()
        
        # 2. Assigned Kuri via staff.group FK
        if staff.group and staff.group.is_active:
            return ChittiGroup.objects.filter(id=staff.group.id)

        # 3. Direct collector filter
        fallback = ChittiGroup.objects.filter(collector=staff, is_active=True)
        if fallback.exists():
            return fallback.distinct()

    elif staff.role in ['admin', 'group_admin']:
        # If admin has a specific active group set on profile, strictly use that group
        if staff.group and staff.group.is_active:
            return ChittiGroup.objects.filter(id=staff.group.id)
        # Otherwise, return their first active group strictly
        owned = ChittiGroup.objects.filter(owner=staff.user, is_active=True)
        if owned.exists():
            return ChittiGroup.objects.filter(id=owned.first().id)

    return ChittiGroup.objects.none()


class CollectorDashboardAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        collector = request.user.staffprofile
        today = timezone.localdate()
        group_id = request.GET.get('group_id') or request.GET.get('group')
        assigned_groups = get_collector_groups(collector, group_id=group_id)

        # TODAY COLLECTION
        today_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date=today,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # MONTHLY COLLECTION
        monthly_collection = Payment.objects.filter(
            collected_by=collector,
            paid_date__year=today.year,
            paid_date__month=today.month,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # TOTAL COLLECTION
        total_collection = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).aggregate(total=Sum('amount'))['total'] or 0

        # ACTIVE MEMBERS
        active_members = Member.objects.filter(
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).distinct().count()

        # REJECTED PAYMENTS
        rejected_qs = Payment.objects.filter(
            collected_by=collector,
            admin_status='rejected',
            payment_status='success'
        )
        rejected_count = rejected_qs.count()
        rejected_amount = rejected_qs.aggregate(total=Sum('amount'))['total'] or 0
        has_rejected = rejected_count > 0

        # RECENT PAYMENTS
        recent_payments = Payment.objects.filter(
            collected_by=collector,
            payment_status='success'
        ).select_related('member', 'group').order_by('-paid_date', '-id')[:10]

        recent_data = [
            {
                "id": payment.id,
                "member": payment.member.name if payment.member else "Unknown",
                "amount": float(payment.amount),
                "date": str(payment.paid_date),
                "admin_status": payment.admin_status,
                "sent_to_admin": payment.sent_to_admin,
                "received_by_admin": payment.received_by_admin,
            }
            for payment in recent_payments
        ]

        # Assigned groups list
        groups_data = [
            {
                "id": g.id,
                "name": g.name,
                "monthly_amount": float(g.monthly_amount),
                "duration_months": g.duration_months
            }
            for g in assigned_groups.filter(is_active=True)
        ]

        return Response({
            "today_collection": float(today_collection),
            "monthly_collection": float(monthly_collection),
            "total_collection": float(total_collection),
            "active_members": active_members,
            "has_rejected": has_rejected,
            "rejected_count": rejected_count,
            "rejected_amount": float(rejected_amount),
            "recent_payments": recent_data,
            "groups": groups_data
        })


class ListMembersAPIView(ListAPIView):
    serializer_class = AssignedMemberSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CollectorPagination

    def get_queryset(self):
        staff = self.request.user.staffprofile
        assigned_groups = get_collector_groups(staff)

        queryset = Member.objects.filter(
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).distinct()

        group_id = self.request.query_params.get('group') or self.request.query_params.get('group_id')
        if group_id:
            try:
                gid = int(group_id)
                queryset = queryset.filter(
                    Q(assigned_chitti_group_id=gid) |
                    Q(chitti_memberships__group_id=gid)
                )
            except (ValueError, TypeError):
                pass

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
        assigned_groups = get_collector_groups(staff)

        member = Member.objects.filter(
            Q(id=member_id),
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).distinct().first()

        if not member:
            return Response({"error": "Member not found in assigned groups"}, status=status.HTTP_404_NOT_FOUND)

        group = None
        if member.assigned_chitti_group and member.assigned_chitti_group in assigned_groups:
            group = member.assigned_chitti_group
        else:
            matched = member.chitti_memberships.filter(group__in=assigned_groups).select_related('group').first()
            if matched and matched.group:
                group = matched.group
        if not group:
            group = member.assigned_chitti_group or (member.chitti_memberships.first().group if member.chitti_memberships.exists() else None)

        if not group:
            return Response({"error": "No Kuri Group assigned to this member"}, status=status.HTTP_400_BAD_REQUEST)

        payments = Payment.objects.filter(
            member=member,
            group=group,
            payment_status='success'
        ).order_by('-paid_date', '-id')

        total_paid = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        start_date = group.start_date if group.start_date else current_date

        total_months = group.duration_months
        monthly_amount = float(group.monthly_amount)
        total_kuri_amount = float(group.total_amount) if group.total_amount else (monthly_amount * total_months)

        temp_total_paid = float(total_paid)
        pending_amount = max(total_kuri_amount - temp_total_paid, 0)

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
                st_label = "Advance" if is_future_month else "Full Paid"
                temp_total_paid -= target
            elif temp_total_paid > 0:
                received = temp_total_paid
                remaining = target - received
                st_label = "Partial"
                temp_total_paid = 0
            else:
                st_label = "Pending"

            month_status.append({
                "month": i,
                "target": target,
                "received": received,
                "remaining": remaining,
                "status": st_label
            })

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
                "paid_date": str(payment.paid_date),
                "amount": float(payment.amount),
                "payment_method": payment.payment_method,
                "collected_by": collected_by,
                "sent_to_admin": payment.sent_to_admin,
                "admin_status": payment.admin_status
            })

        return Response({
            "member": {
                "id": member.id,
                "name": getattr(member, "name", None),
                "phone": getattr(member, "phone", None),
            },
            "group": {
                "id": group.id,
                "name": group.name,
            },
            "summary": {
                "total_months": total_months,
                "kuri_current_month": min(max(1, (current_date.year - start_date.year) * 12 + current_date.month - start_date.month + 1), total_months),
                "monthly_amount": monthly_amount,
                "total_kuri_amount": total_kuri_amount,
                "total_paid": float(total_paid),
                "months_paid": int(float(total_paid) // monthly_amount) if monthly_amount > 0 else 0,
                "due_to_date": float(max(0.0, (monthly_amount * min(max(1, (current_date.year - start_date.year) * 12 + current_date.month - start_date.month + 1), total_months)) - float(total_paid))),
                "pending_amount": float(pending_amount),
            },
            "month_status": month_status,
            "payments": payment_data
        })


# ==================================================
# ➕ Add Collection API (Collector)
# ==================================================
class AddCollectionAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile
        assigned_groups = get_collector_groups(staff)

        member_id = request.query_params.get("member_id") or request.query_params.get("member")

        if member_id:
            member = Member.objects.filter(
                Q(id=member_id),
                Q(assigned_chitti_group__in=assigned_groups) |
                Q(chitti_memberships__group__in=assigned_groups)
            ).distinct().first()

            if not member:
                return Response({"error": "Member not found in assigned groups"}, status=status.HTTP_404_NOT_FOUND)
            group = None
            if member.assigned_chitti_group and member.assigned_chitti_group in assigned_groups:
                group = member.assigned_chitti_group
            else:
                matched = member.chitti_memberships.filter(group__in=assigned_groups).select_related('group').first()
                if matched and matched.group:
                    group = matched.group
            if not group:
                group = member.assigned_chitti_group or (member.chitti_memberships.first().group if member.chitti_memberships.exists() else None)
            
            monthly_amount = Decimal(str(group.monthly_amount))
            duration_months = group.duration_months
            full_total_amount = monthly_amount * duration_months

            total_paid = Payment.objects.filter(
                member=member,
                group=group,
                payment_status='success'
            ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')

            months_covered = int(total_paid // monthly_amount) if monthly_amount > 0 else 0
            progress_percent = min(round(float(total_paid / full_total_amount * 100), 1), 100.0) if full_total_amount > 0 else 0.0

            # Calculate expected months elapsed
            today = timezone.localdate()
            start_date = group.start_date or today
            months_elapsed = max(1, (today.year - start_date.year) * 12 + today.month - start_date.month + 1)
            months_elapsed = min(months_elapsed, duration_months)

            expected_to_date = monthly_amount * months_elapsed

            if total_paid >= full_total_amount:
                pending = Decimal('0.00')
                advance = total_paid - full_total_amount
                current_installment = duration_months
                status_type = 'completed'
                status_text = 'COMPLETED'
                next_action_text = 'Chitti plan is fully paid! 🎉'
            elif total_paid >= expected_to_date:
                pending = Decimal('0.00')
                advance = total_paid - expected_to_date
                current_installment = min(months_covered + 1, duration_months)
                if advance > Decimal('0.00'):
                    status_type = 'advance'
                    status_text = 'IN ADVANCE'
                    next_action_text = f'Advance Paid! Next collection is for Month {current_installment} of {duration_months}'
                else:
                    status_type = 'up_to_date'
                    status_text = 'UP TO DATE'
                    next_action_text = f'Collecting for Month {current_installment} of {duration_months}'
            else:
                pending = expected_to_date - total_paid
                advance = Decimal('0.00')
                current_installment = months_covered + 1
                status_type = 'pending'
                status_text = 'PENDING DUE'
                next_action_text = f'Paying Month {current_installment} (₹{pending:.0f} Pending Due)'

            return Response({
                "member_id": member.id,
                "member_name": member.name,
                "phone": member.phone,
                "group_id": group.id,
                "group_name": group.name,
                "monthly_amount": float(monthly_amount),
                "duration_months": duration_months,
                "total_paid": float(total_paid),
                "full_total_amount": float(full_total_amount),
                "months_covered": months_covered,
                "current_installment": current_installment,
                "kuri_running_month": months_elapsed,
                "months_elapsed": months_elapsed,
                "progress_percent": progress_percent,
                "pending": float(pending),
                "pending_due": float(pending),
                "advance": float(advance),
                "status_type": status_type,
                "status_text": status_text,
                "next_action_text": next_action_text,
                "suggested_amounts": [
                    float(monthly_amount),
                    float(monthly_amount * 2),
                    float(pending) if pending > 0 else float(monthly_amount)
                ]
            })

        # List members for selection
        members = Member.objects.filter(
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).distinct().order_by('name')

        members_data = []
        for m in members:
            relevant_group = None
            if m.assigned_chitti_group and m.assigned_chitti_group in assigned_groups:
                relevant_group = m.assigned_chitti_group
            else:
                matched = m.chitti_memberships.filter(group__in=assigned_groups).select_related('group').first()
                if matched and matched.group:
                    relevant_group = matched.group
            if not relevant_group:
                relevant_group = m.assigned_chitti_group

            members_data.append({
                "id": m.id,
                "name": m.name,
                "phone": m.phone,
                "group_id": relevant_group.id if relevant_group else None,
                "group_name": relevant_group.name if relevant_group else None,
                "monthly_amount": float(relevant_group.monthly_amount) if relevant_group and relevant_group.monthly_amount else 0.0
            })

        return Response({
            "members": members_data
        })

    def post(self, request):
        try:
            staff = request.user.staffprofile
        except:
            return Response(
                {"error": "Staff profile not found"},
                status=status.HTTP_400_BAD_REQUEST
            )

        member_id = request.data.get("member") or request.data.get("member_id")
        amount = request.data.get("amount")
        paid_date_str = request.data.get("paid_date")
        method = request.data.get("payment_method") or "cash"

        if not all([member_id, amount, paid_date_str]):
            return Response(
                {"error": "Member, amount, and date are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        assigned_groups = get_collector_groups(staff)

        member = Member.objects.filter(
            Q(id=member_id),
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).distinct().first()

        if not member:
            return Response({"error": "Member not found in assigned groups"}, status=status.HTTP_404_NOT_FOUND)

        group = None
        if member.assigned_chitti_group and member.assigned_chitti_group in assigned_groups:
            group = member.assigned_chitti_group
        else:
            matched = member.chitti_memberships.filter(group__in=assigned_groups).select_related('group').first()
            if matched and matched.group:
                group = matched.group
        if not group:
            group = member.assigned_chitti_group or (member.chitti_memberships.first().group if member.chitti_memberships.exists() else None)

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

        if actual_paid >= full_total_amount:
            return Response(
                {"error": f"{member.name} has already completed full payment (₹{full_total_amount:,.0f}). No further payment allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if actual_paid + amount > full_total_amount:
            remaining = full_total_amount - actual_paid
            return Response(
                {"error": f"Payment exceeds full total! Only ₹{remaining:,.0f} allowed to complete scheme."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # -----------------------------
        # ✅ CREATE PAYMENT (FULL FLOW)
        # -----------------------------
        payment = Payment.objects.create(
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

        # 🚀 Send Instant Push Notification to Member
        if member and member.user:
            try:
                from core.fcm_service import send_push_to_user
                col_name = staff.user.get_full_name() or staff.user.username if staff.user else "Collector"
                send_push_to_user(
                    user=member.user,
                    title=f"🧾 Payment Received: ₹{float(amount):,.0f}",
                    body=f"₹{float(amount):,.0f} received via {col_name} for '{group.name}'.",
                    data={"type": "receipt", "payment_id": str(payment.id), "group_id": str(group.id), "portal": "member"}
                )
            except Exception:
                pass

        # 🚀 Send Instant Push Notification to Group Admin
        if group and group.owner:
            try:
                from core.fcm_service import send_push_to_user
                col_name = staff.user.get_full_name() or staff.user.username if staff.user else "Collector"
                send_push_to_user(
                    user=group.owner,
                    title=f"💵 New Collection: ₹{float(amount):,.0f}",
                    body=f"{col_name} collected ₹{float(amount):,.0f} from {member.name} for '{group.name}'.",
                    data={"type": "collection", "payment_id": str(payment.id), "group_id": str(group.id), "portal": "admin"}
                )
            except Exception:
                pass

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

        # ✅ Mark as sent & ensure notification triggers for admin
        first_pay = payments.first()
        payments.update(
            sent_to_admin=True,
            admin_status='pending',
            is_seen=False
        )

        try:
            from core.fcm_service import send_push_to_user
            if first_pay and first_pay.group and first_pay.group.owner:
                col_name = staff.user.get_full_name() or staff.user.username if (staff and staff.user) else "Collector"
                send_push_to_user(
                    user=first_pay.group.owner,
                    title=f"🔔 {payments.count()} Cash Handover Pending",
                    body=f"{col_name} sent ₹{float(total_amount):,.0f} cash collection handover for your approval.",
                    data={"type": "handover", "portal": "admin", "group_id": str(first_pay.group.id)}
                )
        except Exception:
            pass

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

        # 🔁 Reset & resend (triggers admin notification)
        payment.admin_status = 'pending'
        payment.sent_to_admin = True
        payment.received_by_admin = False
        payment.is_seen = False
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

        # ⚡ Bulk update (fast, triggers admin notification)
        payments.update(
            admin_status='pending',
            sent_to_admin=True,
            received_by_admin=False,
            is_seen=False
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
        ).select_related('member', 'group').order_by('-id')

        total_collected = payments.aggregate(total=Sum('amount'))['total'] or 0

        rejected_payments = payments.filter(admin_status='rejected')
        rejected_count = rejected_payments.count()
        rejected_amount = rejected_payments.aggregate(total=Sum('amount'))['total'] or 0

        payment_data = [
            {
                "id": p.id,
                "member": p.member.name if p.member else None,  
                "amount": float(p.amount),
                "payment_method": p.payment_method,
                "paid_date": str(p.paid_date),
                "admin_status": p.admin_status,
                "sent_to_admin": p.sent_to_admin,
                "received_by_admin": p.received_by_admin,
                "group_id": p.group.id if p.group else None,
                "group_name": p.group.name if p.group else None,
            }
            for p in payments
        ]

        return Response({
            "total_collected": float(total_collected),
            "has_rejected": rejected_count > 0,
            "rejected_count": rejected_count,
            "rejected_amount": float(rejected_amount),
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
        status_filter = request.GET.get('status', 'pending').lower().strip()

        assigned_groups = get_collector_groups(staff)
        members = Member.objects.filter(
            Q(assigned_chitti_group__in=assigned_groups) |
            Q(chitti_memberships__group__in=assigned_groups)
        ).select_related('assigned_chitti_group').distinct()

        member_list = []

        for member in members:
            # Determine group
            group = member.assigned_chitti_group
            if not group:
                cm = ChittiMember.objects.filter(member=member, group__in=assigned_groups).select_related('group').first()
                group = cm.group if cm else None

            if not group:
                continue

            monthly_amount = float(group.monthly_amount or 0)
            if monthly_amount <= 0:
                continue

            start_date = group.start_date or today
            duration_months = int(group.duration_months or 1)
            months_elapsed = max(1, (today.year - start_date.year) * 12 + today.month - start_date.month + 1)
            current_month = min(months_elapsed, duration_months)

            # Calculate total paid for this group
            total_paid = float(Payment.objects.filter(
                member=member,
                group=group,
                payment_status='success'
            ).aggregate(total=Sum('amount'))['total'] or 0)

            full_total_amount = monthly_amount * duration_months
            expected_paid = current_month * monthly_amount
            due_amount = max(0.0, expected_paid - total_paid)

            month_label = f"Month {current_month} of {duration_months} ({today.strftime('%b %Y')})"

            is_paid = (due_amount <= 0.0) or (total_paid >= expected_paid)

            if status_filter in ["pending", "due", "dues"] and not is_paid:
                member_list.append({
                    'member_name': member.name,
                    'member_id': member.id,
                    'group': group.name,
                    'month': month_label,
                    'paid': total_paid,
                    'due': due_amount,
                    'status': 'Pending'
                })
            elif status_filter in ["paid", "success", "cleared", "completed"] and is_paid:
                member_list.append({
                    'member_name': member.name,
                    'member_id': member.id,
                    'group': group.name,
                    'month': month_label,
                    'paid': total_paid,
                    'due': 0.0,
                    'status': 'Cleared' if total_paid >= full_total_amount else 'Up to Date'
                })

        return Response({
            "status_filter": status_filter,
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
        from_date = request.GET.get('from') or request.GET.get('from_date')
        to_date = request.GET.get('to') or request.GET.get('to_date')

        if from_date or to_date:
            filtered_qs = qs
            if from_date:
                try:
                    from_date_obj = datetime.strptime(from_date.strip()[:10], "%Y-%m-%d").date()
                    filtered_qs = filtered_qs.filter(paid_date__gte=from_date_obj)
                except Exception:
                    pass
            if to_date:
                try:
                    to_date_obj = datetime.strptime(to_date.strip()[:10], "%Y-%m-%d").date()
                    filtered_qs = filtered_qs.filter(paid_date__lte=to_date_obj)
                except Exception:
                    pass
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

        assigned_groups = get_collector_groups(collector)
        group_names = [g.name for g in assigned_groups]
        groups_data = [
            {
                "id": g.id,
                "name": g.name,
                "code": g.code,
                "monthly_amount": float(g.monthly_amount),
                "duration_months": g.duration_months,
                "total_amount": float(g.total_amount) if g.total_amount else float(g.monthly_amount) * g.duration_months
            }
            for g in assigned_groups
        ]

        return Response({
            "collector": {
                "id": collector.id,
                "username": collector.user.username,
                "phone": collector.phone,   
                "email": collector.user.email,
                "joined": collector.user.date_joined.strftime("%d %b %Y"),
            },
            "assigned_groups": group_names,
            "groups": groups_data
        })


class CollectorRejectedPaymentsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        staff = request.user.staffprofile
        collector_groups = set()
        if staff.group:
            collector_groups.add(staff.group.id)
        if hasattr(staff, 'assigned_chitti_groups'):
            collector_groups.update(staff.assigned_chitti_groups.values_list('id', flat=True))

        rejected_payments = Payment.objects.filter(
            Q(collected_by=staff) | Q(collected_by__user=request.user) | Q(group__collector=staff) | Q(group_id__in=collector_groups),
            admin_status='rejected',
            payment_status='success'
        ).select_related('member', 'group').order_by('-paid_date', '-id')

        total_rejected_amount = rejected_payments.aggregate(total=Sum('amount'))['total'] or 0

        # Group by Kuri group
        by_group = defaultdict(list)
        for p in rejected_payments:
            g_name = p.group.name if p.group else "General"
            g_id = p.group.id if p.group else 0
            by_group[(g_id, g_name)].append(p)

        groups_data = []
        for (g_id, g_name), p_list in by_group.items():
            g_total = sum(p.amount for p in p_list)
            groups_data.append({
                "group_id": g_id,
                "group_name": g_name,
                "total_amount": float(g_total),
                "count": len(p_list),
                "payments": [
                    {
                        "id": p.id,
                        "member_name": p.member.name if p.member else "Unknown",
                        "member_phone": p.member.phone if p.member else "",
                        "amount": float(p.amount),
                        "paid_date": str(p.paid_date),
                        "payment_method": p.payment_method,
                        "group_id": g_id,
                        "group_name": g_name,
                        "admin_status": p.admin_status,
                    }
                    for p in p_list
                ]
            })

        flat_payments = [
            {
                "id": p.id,
                "member_name": p.member.name if p.member else "Unknown",
                "member_phone": p.member.phone if p.member else "",
                "amount": float(p.amount),
                "paid_date": str(p.paid_date),
                "payment_method": p.payment_method,
                "group_id": p.group.id if p.group else None,
                "group_name": p.group.name if p.group else None,
                "admin_status": p.admin_status,
            }
            for p in rejected_payments
        ]

        return Response({
            "has_rejected": rejected_payments.exists(),
            "total_count": rejected_payments.count(),
            "total_amount": float(total_rejected_amount),
            "groups": groups_data,
            "payments": flat_payments,
        })