from collections import defaultdict

from django.db.models import Sum
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, status
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from chitti.models import ChittiGroup, ChittiMember, GroupInvitation
from payments.models import Payment, Installment
from members.models import Member
from accounts.models import StaffProfile
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
        admin_groups = ChittiGroup.objects.filter(owner=request.user)

        group_ids = set(admin_groups.values_list('id', flat=True))

        if staff_profile and staff_profile.group:
            group_ids.add(staff_profile.group.id)
            for sg_id in staff_profile.group.sub_groups.values_list('id', flat=True):
                group_ids.add(sg_id)

        if staff_profile:
            for g in staff_profile.assigned_chitti_groups.values_list('id', flat=True):
                group_ids.add(g)

        if not group_ids:
            return Response(
                {"error": "You are not assigned to any group."},
                status=status.HTTP_400_BAD_REQUEST
            )

        filter_group_id = request.GET.get('group_id')
        if filter_group_id:
            try:
                fid = int(filter_group_id)
                if fid in group_ids or request.user.is_superuser or (staff_profile and staff_profile.role == 'admin'):
                    group_ids = [fid]
                else:
                    return Response({"error": "Permission denied for this group."}, status=403)
            except (ValueError, TypeError):
                pass

        # ✅ Fetch payments strictly scoped to authorized groups
        payments_qs = Payment.objects.filter(group_id__in=group_ids) \
            .select_related('member', 'collected_by', 'group')

        # =====================================================
        # 🔥 ADVANCED FILTERS (DATE RANGE, METHOD, SEARCH)
        # =====================================================
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        if from_date:
            payments_qs = payments_qs.filter(paid_date__gte=from_date)
        if to_date:
            payments_qs = payments_qs.filter(paid_date__lte=to_date)

        payment_method = request.GET.get('payment_method')
        if payment_method and payment_method != 'all':
            payments_qs = payments_qs.filter(payment_method__icontains=payment_method)

        filter_group_id = request.GET.get('group_id')
        if filter_group_id:
            payments_qs = payments_qs.filter(group_id=filter_group_id)

        query = request.GET.get('q', '').strip()
        if query:
            from django.db.models import Q
            payments_qs = payments_qs.filter(
                Q(member__name__icontains=query) |
                Q(collected_by__user__username__icontains=query) |
                Q(payment_method__icontains=query)
            )

        payments_qs = payments_qs.order_by('-paid_date', '-id')

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
        # 🔥 PAGINATION
        # =====================================================
        page_number = request.GET.get('page', 1)
        page_size = int(request.GET.get('page_size', 50))

        paginator = Paginator(payments_qs, page_size)
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
        # 🔒 TOTAL LIMIT CHECK (IMPORTANT 🔥)
        # =========================
        full_total_amount = float(group.monthly_amount) * group.duration_months
        actual_paid_before = float(
            Payment.objects.filter(
                member=member,
                group=group,
                payment_status='success'
            ).aggregate(total=Sum('amount'))['total'] or 0.0
        )

        amount_val = float(amount)
        if actual_paid_before >= full_total_amount:
            return Response(
                {"error": f"{member.name} has already completed full payment (₹{full_total_amount:,.0f}). No further payment allowed."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if actual_paid_before + amount_val > full_total_amount:
            remaining = full_total_amount - actual_paid_before
            return Response(
                {"error": f"Payment exceeds full total! Only ₹{remaining:,.0f} allowed to complete scheme."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # =========================
        # CREATE PAYMENT
        # =========================
        is_direct_admin = (staff_profile.role in ['group_admin', 'admin'] or group.owner == request.user or request.user.is_superuser)
        payment = Payment.objects.create(
            member=member,
            group=group,
            amount=amount_val,
            paid_date=timezone.now().date(),
            payment_status="success",
            collected_by=staff_profile,
            sent_to_admin=True,
            admin_status='approved' if is_direct_admin else 'pending',
            received_by_admin=True if is_direct_admin else False
        )

        # 🚀 Send Instant Push Notification to Member
        if member and member.user:
            try:
                from core.fcm_service import send_push_to_user
                send_push_to_user(
                    user=member.user,
                    title=f"🧾 Payment Received: ₹{float(amount_val):,.0f}",
                    body=f"Payment of ₹{float(amount_val):,.0f} recorded for '{group.name}'.",
                    data={"type": "receipt", "payment_id": str(payment.id), "group_id": str(group.id), "portal": "member"}
                )
            except Exception:
                pass

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
            profile_query = Q()
            if request.user.email:
                profile_query |= Q(user__email__iexact=request.user.email)
            if request.user.username:
                profile_query |= Q(user__username=request.user.username)
            if profile_query:
                staff = StaffProfile.objects.filter(profile_query).first()

        owner_filter = Q(owner=request.user)
        if request.user.email:
            owner_filter |= Q(owner__email__iexact=request.user.email)
        if request.user.username:
            owner_filter |= Q(owner__username=request.user.username)
        is_group_owner = ChittiGroup.objects.filter(owner_filter).exists()

        if not staff and not is_group_owner:
            return Response({"error": "No staff profile"}, status=400)

        # 🔹 Role-based group access
        if staff and staff.role == 'admin':
            groups = ChittiGroup.objects.all()
        else:
            group_filter = owner_filter
            if staff:
                group_filter |= Q(collector=staff)
            groups = ChittiGroup.objects.filter(group_filter).distinct()

        filter_group_id = request.GET.get('group_id')
        if filter_group_id:
            try:
                groups = groups.filter(id=int(filter_group_id))
            except (ValueError, TypeError):
                pass

        payments = Payment.objects.filter(
            payment_status='success',
            group__in=groups,
            collected_by__isnull=False,
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

                "total_pending": float(sum(p.amount for p in pending)),
                "total_approved": float(sum(p.amount for p in approved)),
                "total_rejected": float(sum(p.amount for p in rejected)),

                "count_pending": len(pending),
                "count_approved": len(approved),
                "count_rejected": len(rejected),

                "pending_payments": [
                    {
                        "id": p.id,
                        "member": p.member.name if p.member else "Member",
                        "amount": float(p.amount),
                        "date": str(p.paid_date),
                        "collected_by": p.collected_by.user.username if p.collected_by else "Staff"
                    } for p in pending
                ],
                "approved_payments": [
                    {
                        "id": p.id,
                        "member": p.member.name if p.member else "Member",
                        "amount": float(p.amount),
                        "date": str(p.paid_date),
                    } for p in approved
                ]
            })

        return Response({"groups": group_list})


# ============================================
# 🔥 GROUP PAYMENT DETAILS API
# ============================================
class GroupPaymentDetailsAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, group_id):
        from django.db.models import Q
        staff = getattr(request.user, "staffprofile", None)

        if not staff:
            return Response({"error": "No staff profile"}, status=400)

        if staff.role == 'admin':
            group = get_object_or_404(ChittiGroup, id=group_id)
        else:
            group = get_object_or_404(
                ChittiGroup,
                Q(id=group_id),
                Q(owner=request.user) | Q(collector=staff)
            )

        payments = Payment.objects.filter(
            group=group,
            payment_status='success',
            collected_by__isnull=False,
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

        # 🚀 Send Instant Push Notification to Member and Collector
        try:
            from core.fcm_service import send_push_to_user
            member_name = payment.member.name if payment.member else "Member"
            approve_title = f"🎉 Payment Approved: ₹{float(payment.amount):,.0f}"

            if payment.member and payment.member.user:
                send_push_to_user(
                    user=payment.member.user,
                    title=approve_title,
                    body=f"Your payment of ₹{float(payment.amount):,.0f} has been verified and approved by admin.",
                    data={"type": "approval", "payment_id": str(payment.id), "portal": "member"}
                )

            if payment.collected_by and payment.collected_by.user:
                send_push_to_user(
                    user=payment.collected_by.user,
                    title=f"✅ Collection Approved: ₹{float(payment.amount):,.0f}",
                    body=f"Collection of ₹{float(payment.amount):,.0f} from {member_name} has been approved by admin.",
                    data={"type": "approval", "payment_id": str(payment.id), "portal": "collector"}
                )
        except Exception as e:
            logger.error(f"FCM push error on payment approve: {e}")

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

        # 🚀 Send Instant WhatsApp-style Push Notification to Collector and Member
        try:
            from core.fcm_service import send_push_to_user
            member_name = payment.member.name if payment.member else "Member"
            rejection_title = f"❌ Collection Rejected: ₹{float(payment.amount):,.0f}"
            rejection_body = f"Collection of ₹{float(payment.amount):,.0f} from {member_name} was rejected by admin. Tap to review."

            if payment.collected_by and payment.collected_by.user:
                send_push_to_user(
                    user=payment.collected_by.user,
                    title=rejection_title,
                    body=rejection_body,
                    data={"type": "rejection", "payment_id": str(payment.id), "portal": "collector"}
                )

            if payment.member and payment.member.user:
                send_push_to_user(
                    user=payment.member.user,
                    title=f"❌ Payment Rejected: ₹{float(payment.amount):,.0f}",
                    body=f"Your payment of ₹{float(payment.amount):,.0f} was rejected by admin. Please contact your collector.",
                    data={"type": "rejection", "payment_id": str(payment.id), "portal": "member"}
                )
        except Exception as e:
            logger.error(f"FCM push error on payment reject: {e}")

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

            try:
                from core.fcm_service import send_push_to_user
                member_name = p.member.name if p.member else "Member"
                if p.member and p.member.user:
                    send_push_to_user(
                        user=p.member.user,
                        title=f"🎉 Payment Approved: ₹{float(p.amount):,.0f}",
                        body=f"Your payment of ₹{float(p.amount):,.0f} has been verified and approved by admin.",
                        data={"type": "approval", "payment_id": str(p.id), "portal": "member"}
                    )
                if p.collected_by and p.collected_by.user:
                    send_push_to_user(
                        user=p.collected_by.user,
                        title=f"✅ Collection Approved: ₹{float(p.amount):,.0f}",
                        body=f"Collection of ₹{float(p.amount):,.0f} from {member_name} has been approved by admin.",
                        data={"type": "approval", "payment_id": str(p.id), "portal": "collector"}
                    )
            except Exception:
                pass

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

            try:
                from core.fcm_service import send_push_to_user
                member_name = p.member.name if p.member else "Member"
                if p.collected_by and p.collected_by.user:
                    send_push_to_user(
                        user=p.collected_by.user,
                        title=f"❌ Collection Rejected: ₹{float(p.amount):,.0f}",
                        body=f"Collection of ₹{float(p.amount):,.0f} from {member_name} was rejected by admin. Tap to review.",
                        data={"type": "rejection", "payment_id": str(p.id), "portal": "collector"}
                    )
                if p.member and p.member.user:
                    send_push_to_user(
                        user=p.member.user,
                        title=f"❌ Payment Rejected: ₹{float(p.amount):,.0f}",
                        body=f"Your payment of ₹{float(p.amount):,.0f} was rejected by admin. Please contact your collector.",
                        data={"type": "rejection", "payment_id": str(p.id), "portal": "member"}
                    )
            except Exception:
                pass

        return Response({
            "message": "All payments rejected",
            "total_amount": total
        })


# ============================================
# 🔔 ADMIN & COLLECTOR NOTIFICATION API
# ============================================
from django.db.models import Sum, Count, Q

def get_all_subgroup_ids(group):
    if not group:
        return []
    ids = [group.id]
    children = group.sub_groups.all()
    for child in children:
        ids.extend(get_all_subgroup_ids(child))
    return ids


def get_admin_accessible_group_ids(user, staff=None):
    if staff and staff.role == 'admin':
        return list(ChittiGroup.objects.values_list('id', flat=True))

    group_ids = set()
    if staff and staff.group:
        group_ids.update(get_all_subgroup_ids(staff.group))

    owned_filter = Q(owner=user) | Q(parent_group__owner=user)
    if user.email:
        owned_filter |= Q(owner__email__iexact=user.email) | Q(parent_group__owner__email__iexact=user.email)
    if user.username:
        owned_filter |= Q(owner__username=user.username) | Q(parent_group__owner__username=user.username)
    if staff:
        owned_filter |= Q(collector=staff)

    owned_groups = ChittiGroup.objects.filter(owned_filter)
    for g in owned_groups:
        group_ids.update(get_all_subgroup_ids(g))

    return list(group_ids)


class AdminNotificationAPI(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        portal = request.query_params.get('portal', '').lower().strip()
        group_id = request.query_params.get('group_id') or request.query_params.get('group')
        gid = None
        if group_id:
            try:
                gid = int(group_id)
            except (ValueError, TypeError):
                pass

        staff = getattr(request.user, "staffprofile", None)
        if not staff:
            profile_query = Q()
            if request.user.email:
                profile_query |= Q(user__email__iexact=request.user.email)
            if request.user.username:
                profile_query |= Q(user__username=request.user.username)
            if profile_query:
                if portal in ['admin', 'group_admin']:
                    staff = StaffProfile.objects.filter(profile_query, role__in=['admin', 'group_admin']).first()
                elif portal == 'collector':
                    staff = StaffProfile.objects.filter(profile_query, role='collector').first()
                if not staff:
                    staff = StaffProfile.objects.filter(profile_query).first()

        owner_filter = Q(owner=request.user)
        if request.user.email:
            owner_filter |= Q(owner__email__iexact=request.user.email)
        if request.user.username:
            owner_filter |= Q(owner__username=request.user.username)
        is_group_owner = ChittiGroup.objects.filter(owner_filter).exists()
        member_profile = getattr(request.user, "member_profile", None)

        notifications = []
        pending_groups = []
        total_pending_count = 0
        rejected_count = 0
        total_rejected_amount = 0.0

        # Helper to get collector groups
        collector_groups = set()
        if staff:
            if staff.group:
                collector_groups.add(staff.group.id)
            if hasattr(staff, 'assigned_chitti_groups'):
                collector_groups.update(staff.assigned_chitti_groups.values_list('id', flat=True))
        if request.user.email:
            col_staffs = StaffProfile.objects.filter(user__email__iexact=request.user.email, role='collector')
            for cs in col_staffs:
                if cs.group:
                    collector_groups.add(cs.group.id)
                if hasattr(cs, 'assigned_chitti_groups'):
                    collector_groups.update(cs.assigned_chitti_groups.values_list('id', flat=True))

        # ── 1. GROUP ADMIN NOTIFICATIONS ──────────────────────────────────────
        admin_notifications = []
        if (staff or is_group_owner) and (portal in ['admin', 'group_admin'] or not portal):
            admin_group_ids = get_admin_accessible_group_ids(request.user, staff)
            if gid:
                admin_group_ids = [g for g in admin_group_ids if g == gid]

            admin_qs = Payment.objects.filter(
                sent_to_admin=True,
                admin_status__iexact='pending',
                is_seen=False
            )

            if not staff or staff.role != 'admin':
                if admin_group_ids:
                    admin_qs = admin_qs.filter(group_id__in=admin_group_ids)
                else:
                    admin_qs = admin_qs.filter(
                        Q(group__owner=request.user) |
                        (Q(group__owner__email__iexact=request.user.email) if request.user.email else Q()) |
                        (Q(group__collector=staff) if staff else Q())
                    )

            total_pending_count = admin_qs.count()
            if total_pending_count > 0:
                pending_groups = list(
                    admin_qs.values(
                        'group__id',
                        'group__name'
                    ).annotate(
                        total_pending=Sum('amount'),
                        entry_count=Count('id')
                    )
                )
                group_names = ", ".join([g['group__name'] for g in pending_groups if g.get('group__name')])
                total_amt = sum([float(g['total_pending'] or 0) for g in pending_groups])
                first_item = admin_qs.order_by('-updated_at', '-id').first()
                admin_notifications.append({
                    "id": first_item.id if first_item else 1,
                    "title": f"🔔 {total_pending_count} Cash Handover{'s' if total_pending_count > 1 else ''} Pending",
                    "message": f"Collections pending approval in: {group_names}" if group_names else "You have pending cash collections to approve.",
                    "created_at": first_item.updated_at.isoformat() if (first_item and hasattr(first_item, 'updated_at') and first_item.updated_at) else timezone.now().isoformat(),
                    "amount": total_amt,
                    "count": total_pending_count,
                    "type": "handover",
                    "priority": "high",
                })

            # New Collections by Collectors for Admin's groups
            new_col_qs = Payment.objects.filter(
                payment_status='success',
                collected_by__isnull=False
            ).select_related('collected_by__user', 'member', 'group')

            if not staff or staff.role != 'admin':
                if admin_group_ids:
                    new_col_qs = new_col_qs.filter(group_id__in=admin_group_ids)
                else:
                    new_col_qs = new_col_qs.filter(
                        Q(group__owner=request.user) |
                        (Q(group__owner__email__iexact=request.user.email) if request.user.email else Q())
                    )
            elif gid:
                new_col_qs = new_col_qs.filter(group_id=gid)

            for col in new_col_qs.order_by('-created_at', '-id')[:5]:
                col_staff_name = col.collected_by.user.get_full_name() or col.collected_by.user.username if (col.collected_by and col.collected_by.user) else "Collector"
                admin_notifications.append({
                    "id": col.id + 50000,
                    "title": f"💵 New Collection: ₹{float(col.amount):,.0f}",
                    "message": f"{col_staff_name} collected ₹{float(col.amount):,.0f} from {col.member.name if col.member else 'Member'} for '{col.group.name if col.group else 'Kuri'}'.",
                    "created_at": col.created_at.isoformat() if (hasattr(col, 'created_at') and col.created_at) else timezone.now().isoformat(),
                    "amount": float(col.amount),
                    "count": 1,
                    "type": "collection",
                    "priority": "high",
                })

            # Multi-month pending defaulters in admin groups
            if admin_group_ids or (staff and staff.role == 'admin'):
                members_query = Member.objects.filter(status='active')
                if (not staff or staff.role != 'admin') and admin_group_ids:
                    members_query = members_query.filter(assigned_chitti_group_id__in=admin_group_ids)

                defaulter_count = 0
                total_defaulter_dues = 0.0
                for m in members_query[:60]:
                    unpaid_inst = Installment.objects.filter(member=m, status__in=['pending', 'partial'])
                    if gid:
                        unpaid_inst = unpaid_inst.filter(group_id=gid)
                    if unpaid_inst.count() >= 2:
                        defaulter_count += 1
                        total_defaulter_dues += sum([float(i.amount_due - i.amount_paid) for i in unpaid_inst])

                if defaulter_count > 0:
                    admin_notifications.append({
                        "id": 9991,
                        "title": f"⚠️ Dues Alert: {defaulter_count} Multi-Month Defaulter{'s' if defaulter_count > 1 else ''}",
                        "message": f"{defaulter_count} members across your groups have 2+ unpaid installments (Total: ₹{total_defaulter_dues:,.0f}).",
                        "created_at": timezone.now().isoformat(),
                        "amount": total_defaulter_dues,
                        "count": defaulter_count,
                        "type": "multi_due",
                        "priority": "medium",
                    })

            # New members joined (accepted invitations in past 48h)
            inv_filter = Q(status=GroupInvitation.STATUS_ACCEPTED)
            if (not staff or staff.role != 'admin') and admin_group_ids:
                inv_filter &= Q(group_id__in=admin_group_ids)
            else:
                inv_filter &= (Q(group__owner=request.user) | (Q(group__owner__email__iexact=request.user.email) if request.user.email else Q()))
            if gid:
                inv_filter &= Q(group_id=gid)

            recent_accepted = GroupInvitation.objects.filter(
                inv_filter,
                updated_at__gte=timezone.now() - timezone.timedelta(days=2)
            ).select_related('group', 'member').order_by('-updated_at')

            if recent_accepted.exists():
                acc = recent_accepted.first()
                m_name = acc.member.name if acc.member else "A member"
                admin_notifications.append({
                    "id": acc.id + 70000,
                    "title": f"🎉 {m_name} Joined {acc.group.name}!",
                    "message": f"{m_name} accepted the invitation and joined '{acc.group.name}'.",
                    "created_at": acc.updated_at.isoformat(),
                    "amount": float(acc.group.monthly_amount or 0),
                    "count": recent_accepted.count(),
                    "type": "member_joined",
                    "priority": "normal",
                })

        # ── 2. COLLECTOR NOTIFICATIONS ─────────────────────────────────────────
        collector_notifications = []
        is_collector_role = (staff and staff.role == 'collector') or portal == 'collector'
        if not is_collector_role and request.user.email:
            is_collector_role = StaffProfile.objects.filter(user__email__iexact=request.user.email, role='collector').exists()

        if is_collector_role or not portal:
            col_filter = (
                Q(collected_by__user=request.user) |
                (Q(collected_by=staff) if staff else Q()) |
                (Q(group__collector=staff) if staff else Q()) |
                (Q(collected_by__user__email__iexact=request.user.email) if request.user.email else Q()) |
                (Q(group_id__in=collector_groups) if collector_groups else Q())
            )
            if gid:
                col_filter &= Q(group_id=gid)
            rejected_qs = Payment.objects.filter(
                col_filter,
                admin_status='rejected',
                payment_status='success'
            ).select_related('member', 'group').order_by('-updated_at', '-id')

            rejected_count = rejected_qs.count()
            total_rejected_amount = rejected_qs.aggregate(total=Sum('amount'))['total'] or 0

            if rejected_count > 0:
                for rej in rejected_qs[:10]:
                    m_name = rej.member.name if rej.member else "Member"
                    g_name = rej.group.name if rej.group else "Kuri Group"
                    collector_notifications.append({
                        "id": rej.id + 60000,
                        "title": f"❌ Collection Rejected: ₹{float(rej.amount):,.0f}",
                        "message": f"Collection of ₹{float(rej.amount):,.0f} from {m_name} was rejected by admin. Tap to review.",
                        "created_at": rej.updated_at.isoformat() if hasattr(rej, 'updated_at') and rej.updated_at else timezone.now().isoformat(),
                        "amount": float(rej.amount),
                        "count": 1,
                        "type": "rejection",
                        "priority": "high",
                    })

            # Multi-Month Dues in Collector's assigned route
            active_col_groups = [gid] if (gid and gid in collector_groups) else collector_groups
            if active_col_groups:
                col_members = Member.objects.filter(assigned_chitti_group_id__in=active_col_groups, status='active')
                route_defaulters = 0
                route_dues = 0.0
                for m in col_members[:40]:
                    unpaid_inst = Installment.objects.filter(member=m, status__in=['pending', 'partial'])
                    if gid:
                        unpaid_inst = unpaid_inst.filter(group_id=gid)
                    if unpaid_inst.count() >= 2:
                        route_defaulters += 1
                        route_dues += sum([float(i.amount_due - i.amount_paid) for i in unpaid_inst])

                if route_defaulters > 0:
                    collector_notifications.append({
                        "id": 9992,
                        "title": f"⚠️ Route Dues: {route_defaulters} Member{'s' if route_defaulters > 1 else ''} Overdue",
                        "message": f"{route_defaulters} assigned members have 2+ unpaid months (Total: ₹{route_dues:,.0f}). Check Dues desk.",
                        "created_at": timezone.now().isoformat(),
                        "amount": route_dues,
                        "count": route_defaulters,
                        "type": "multi_due",
                        "priority": "medium",
                    })

        # ── 3. MEMBER NOTIFICATIONS ────────────────────────────────────────────
        member_notifications = []
        user_filters = Q(user=request.user)
        if request.user.email:
            user_filters |= Q(email__iexact=request.user.email)
        if request.user.username:
            user_filters |= Q(phone=request.user.username)
        user_mems = Member.objects.filter(user_filters)

        if gid:
            user_mems = user_mems.filter(
                Q(assigned_chitti_group_id=gid) | Q(chitti_memberships__group_id=gid)
            ).distinct()

        if user_mems.exists() or member_profile or portal == 'member':
            # 3.1 Pending Kuri Invitations
            pending_invs_qs = GroupInvitation.objects.filter(
                member__in=user_mems,
                status=GroupInvitation.STATUS_PENDING,
                group__is_active=True
            )
            if gid:
                pending_invs_qs = pending_invs_qs.filter(group_id=gid)
            pending_invs = pending_invs_qs.select_related('group', 'invited_by').order_by('-created_at')

            if pending_invs.exists():
                first_inv = pending_invs.first()
                admin_label = first_inv.invited_by.get_full_name() or first_inv.invited_by.username if first_inv.invited_by else "Admin"
                member_notifications.append({
                    "id": first_inv.id + 80000,
                    "title": f"📩 Kuri Invitation: {first_inv.group.name}",
                    "message": f"You are invited by {admin_label} to join '{first_inv.group.name}' (₹{float(first_inv.group.monthly_amount or 0):,.0f}/mo). Tap to review & accept!",
                    "created_at": first_inv.created_at.isoformat(),
                    "amount": float(first_inv.group.monthly_amount or 0),
                    "count": pending_invs.count(),
                    "type": "invitation",
                    "priority": "high",
                })

            # 3.2 Rejected Payments for Member
            rejected_member_pays = Payment.objects.filter(
                member__in=user_mems,
                admin_status='rejected'
            ).select_related('collected_by', 'collected_by__user', 'group').order_by('-updated_at', '-id')[:10]

            for rej in rejected_member_pays:
                grp_name = rej.group.name if rej.group else "Kuri"
                member_notifications.append({
                    "id": rej.id + 60000,
                    "title": f"❌ Payment Rejected: ₹{float(rej.amount):,.0f}",
                    "message": f"Your payment of ₹{float(rej.amount):,.0f} for '{grp_name}' was rejected by admin. Tap to check details.",
                    "created_at": rej.updated_at.isoformat() if hasattr(rej, 'updated_at') and rej.updated_at else timezone.now().isoformat(),
                    "amount": float(rej.amount),
                    "count": 1,
                    "type": "rejection",
                    "priority": "high",
                })

            # 3.3 Recent Payment Receipts (Ordered newest first, exclude rejected!)
            recent_pays_qs = Payment.objects.filter(
                member__in=user_mems,
                payment_status='success'
            ).exclude(admin_status='rejected')
            if gid:
                recent_pays_qs = recent_pays_qs.filter(group_id=gid)
            recent_pays = recent_pays_qs.select_related('collected_by', 'collected_by__user', 'group').order_by('-created_at', '-id')[:5]

            for recent_pay in recent_pays:
                col_name = "Collector"
                if recent_pay.collected_by and hasattr(recent_pay.collected_by, 'user') and recent_pay.collected_by.user:
                    col_name = recent_pay.collected_by.user.get_full_name() or recent_pay.collected_by.user.username
                grp_name = recent_pay.group.name if recent_pay.group else "Kuri"
                is_approved = recent_pay.admin_status == 'approved'
                member_notifications.append({
                    "id": recent_pay.id,
                    "title": f"🎉 Payment Approved: ₹{float(recent_pay.amount):,.0f}" if is_approved else f"🧾 Payment Received: ₹{float(recent_pay.amount):,.0f}",
                    "message": f"Payment of ₹{float(recent_pay.amount):,.0f} paid via {col_name} for '{grp_name}' recorded. Receipt #{recent_pay.invoice_number or recent_pay.id}.",
                    "created_at": (recent_pay.updated_at if is_approved else recent_pay.created_at).isoformat() if hasattr(recent_pay, 'created_at') and recent_pay.created_at else timezone.now().isoformat(),
                    "amount": float(recent_pay.amount),
                    "count": 1,
                    "type": "approval" if is_approved else "receipt",
                    "priority": "high",
                })

            # 3.3 Multi-Month Pending Installment Alert
            unpaid_inst_qs = Installment.objects.filter(member__in=user_mems, status__in=['pending', 'partial'])
            if gid:
                unpaid_inst_qs = unpaid_inst_qs.filter(group_id=gid)
            unpaid_inst = unpaid_inst_qs.order_by('month')
            unpaid_count = unpaid_inst.count()
            if unpaid_count > 0:
                total_due = sum([float(i.amount_due - i.amount_paid) for i in unpaid_inst])
                grp_label = f" for '{unpaid_inst.first().group.name}'" if (unpaid_inst.first() and unpaid_inst.first().group) else ""
                if unpaid_count >= 2:
                    member_notifications.append({
                        "id": 9993,
                        "title": f"⚠️ Urgent: {unpaid_count} Months Installments Due",
                        "message": f"You have {unpaid_count} pending installments{grp_label} (Total: ₹{total_due:,.0f}). Clear dues to participate in monthly auctions.",
                        "created_at": timezone.now().isoformat(),
                        "amount": total_due,
                        "count": unpaid_count,
                        "type": "multi_due",
                        "priority": "high",
                    })
                else:
                    member_notifications.append({
                        "id": 9994,
                        "title": "🔔 Monthly Kuri Installment Due",
                        "message": f"Your current installment of ₹{total_due:,.0f}{grp_label} is pending for this month. Pay via your collector.",
                        "created_at": timezone.now().isoformat(),
                        "amount": total_due,
                        "count": 1,
                        "type": "due",
                        "priority": "normal",
                    })

        # ── 4. Routing based on portal query param ────────────────────────────
        if portal == 'collector':
            active_notifications = collector_notifications
        elif portal in ['admin', 'group_admin']:
            active_notifications = admin_notifications
        elif portal == 'member':
            active_notifications = member_notifications
        else:
            if staff and staff.role == 'collector':
                active_notifications = collector_notifications
            elif member_profile:
                active_notifications = member_notifications
            else:
                active_notifications = admin_notifications or collector_notifications or []

        # Sort all active notifications newest first so the latest event triggers first
        active_notifications.sort(key=lambda x: str(x.get('created_at', '')), reverse=True)

        return Response({
            "pending_groups": pending_groups,
            "total_pending_count": total_pending_count,
            "total_rejected_count": rejected_count,
            "total_rejected_amount": float(total_rejected_amount),
            "notifications": active_notifications
        })


class ClearNotificationAPI(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        portal = request.data.get('portal', '').lower().strip() or request.query_params.get('portal', '').lower().strip()
        staff = getattr(request.user, "staffprofile", None)

        if portal in ['admin', 'group_admin'] or not portal:
            if staff:
                admin_group_ids = get_admin_accessible_group_ids(request.user, staff)
                admin_qs = Payment.objects.filter(
                    sent_to_admin=True,
                    admin_status__iexact='pending',
                    is_seen=False
                )
                if staff.role != 'admin':
                    if admin_group_ids:
                        admin_qs = admin_qs.filter(group_id__in=admin_group_ids)
                    else:
                        admin_qs = admin_qs.filter(
                            Q(group__owner=request.user) | Q(group__collector=staff)
                        )
                updated_count = admin_qs.update(is_seen=True)
            else:
                updated_count = Payment.objects.filter(
                    sent_to_admin=True,
                    admin_status__iexact='pending',
                    is_seen=False
                ).update(is_seen=True)
            return Response({"success": True, "message": "Admin notifications marked as read", "updated": updated_count})

        return Response({"success": True, "message": "Notifications marked as read"})