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
from chitti.models import Auction, ChittiGroup, ChittiMember, GroupInvitation
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

        group_id = request.GET.get("group_id")
        if group_id:
            try:
                gid = int(group_id)
                groups = groups.filter(id=gid)
            except (ValueError, TypeError):
                pass

        members = Member.objects.filter(
            Q(assigned_chitti_group__in=groups) |
            Q(chitti_memberships__group__in=groups)
        ).select_related("assigned_chitti_group", "user").distinct().order_by("id")

        q = request.GET.get("q")
        if q:
            members = members.filter(
                Q(name__icontains=q) |
                Q(phone__icontains=q) |
                Q(assigned_chitti_group__name__icontains=q) |
                Q(chitti_memberships__group__name__icontains=q)
            ).distinct()

        return Response({
            "count": members.count(),
            "results": MemberSerializer(
                members,
                many=True,
                context={"request": request, "group_id": group_id}
            ).data
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

            enrolled_gids = list(
                ChittiMember.objects.filter(
                    Q(member=m) | (Q(member__user_id=uid) if uid else Q())
                ).values_list("group_id", flat=True).distinct()
            )
            if m.assigned_chitti_group_id and m.assigned_chitti_group_id not in enrolled_gids:
                enrolled_gids.append(m.assigned_chitti_group_id)

            results.append({
                "id": m.id,
                "user_id": uid,
                "name": m.name,
                "email": m.email or "",
                "phone": m.phone or "",
                "address": m.address or "",
                "aadhaar_no": m.aadhaar_no or "",
                "current_group": m.assigned_chitti_group.name if m.assigned_chitti_group else "",
                "enrolled_group_ids": enrolled_gids,
            })

        if len(results) < 10:
            users_qs = User.objects.filter(
                Q(email__icontains=query) | Q(username__icontains=query) | Q(first_name__icontains=query)
            ).exclude(id__in=seen_user_ids).select_related("member_profile")[:10]

            for u in users_qs:
                enrolled_gids = list(
                    ChittiMember.objects.filter(
                        member__user=u
                    ).values_list("group_id", flat=True).distinct()
                )

                member_prof = getattr(u, "member_profile", None)
                is_username_email = "@" in u.username
                phone_val = ""
                if member_prof and member_prof.phone and "@" not in member_prof.phone:
                    phone_val = member_prof.phone
                elif not is_username_email:
                    phone_val = u.username

                email_val = (member_prof.email if (member_prof and member_prof.email) else None) or u.email or (u.username if is_username_email else "")

                results.append({
                    "id": member_prof.id if member_prof else 0,
                    "user_id": u.id,
                    "name": member_prof.name if member_prof else (u.get_full_name() or u.username),
                    "email": email_val,
                    "phone": phone_val,
                    "address": member_prof.address if member_prof else "",
                    "aadhaar_no": member_prof.aadhaar_no if member_prof else "",
                    "current_group": member_prof.assigned_chitti_group.name if (member_prof and member_prof.assigned_chitti_group) else "",
                    "enrolled_group_ids": enrolled_gids,
                })

        return Response({
            "exists": len(results) > 0,
            "results": results
        })


# MEMBER CREATE / ENROL (Group Admin)
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

        phone = (data.get("phone") or "").strip()
        email = (data.get("email") or "").strip()
        name = (data.get("name") or "").strip()
        address = (data.get("address") or "").strip()
        aadhaar_no = (data.get("aadhaar_no") or "").strip()
        password = data.get("password") or ""
        existing_user_id = request.data.get("existing_user_id")

        try:
            with transaction.atomic():
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

                # Check duplicate inside this group (strictly prevent 2 times in same kuri)
                if group:
                    dup_query = Q()
                    if user:
                        dup_query |= Q(member__user=user)
                    if phone:
                        dup_query |= Q(member__phone=phone) | Q(member__user__username=phone)
                    if email:
                        dup_query |= Q(member__email=email) | Q(member__user__email=email)

                    if dup_query and ChittiMember.objects.filter(group=group).filter(dup_query).exists():
                        return Response(
                            {"detail": f"Member is already enrolled in group '{group.name}'"},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                if user:
                    # Existing User Found -> Find or Create Member profile
                    member = Member.objects.filter(user=user).first()
                    if not member:
                        clean_phone = phone if (phone and "@" not in phone) else ""
                        if not clean_phone and user.username and "@" not in user.username and len(user.username) <= 15:
                            clean_phone = user.username

                        if not clean_phone:
                            return Response(
                                {"detail": "A valid 10-digit mobile number is required to create member profile."},
                                status=status.HTTP_400_BAD_REQUEST
                            )

                        if Member.objects.filter(phone=clean_phone).exists():
                            return Response(
                                {"detail": f"Mobile number '{clean_phone}' is already registered with another member."},
                                status=status.HTTP_400_BAD_REQUEST
                            )

                        member = Member.objects.create(
                            user=user,
                            name=name or user.get_full_name() or user.username,
                            email=email or user.email,
                            phone=clean_phone,
                            address=address,
                            aadhaar_no=aadhaar_no,
                            assigned_chitti_group=group,
                            is_first_login=False
                        )
                    else:
                        # Existing member profile: update details safely
                        if phone and phone != member.phone:
                            if Member.objects.filter(phone=phone).exclude(id=member.id).exists() or User.objects.filter(username=phone).exclude(id=user.id).exists():
                                return Response(
                                    {"detail": f"Mobile number '{phone}' is already registered with another member."},
                                    status=status.HTTP_400_BAD_REQUEST
                                )
                            member.phone = phone
                            if "@" in user.username:
                                user.username = phone
                                user.save()

                        if email and email.lower() != (member.email or "").lower():
                            if Member.objects.filter(email__iexact=email).exclude(id=member.id).exists() or User.objects.filter(email__iexact=email).exclude(id=user.id).exists():
                                return Response(
                                    {"detail": f"Email '{email}' is already registered with another member."},
                                    status=status.HTTP_400_BAD_REQUEST
                                )
                            member.email = email
                            if not user.email:
                                user.email = email
                                user.save()

                        if address:
                            member.address = address
                        if aadhaar_no:
                            member.aadhaar_no = aadhaar_no
                        member.save()

                    # 🛡️ Method 2: Consent-based Invitation for Existing Member
                    # Check if already enrolled in this group
                    if group and ChittiMember.objects.filter(group=group, member=member).exists():
                        return Response(
                            {"detail": f"Member is already enrolled in group '{group.name}'"},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    # Check if an invitation is already pending
                    invitation_id = None
                    if group:
                        pending_inv = GroupInvitation.objects.filter(
                            group=group,
                            member=member,
                            status=GroupInvitation.STATUS_PENDING
                        ).first()
                        if pending_inv:
                            return Response(
                                {"detail": f"An invitation is already pending for {member.name} in group '{group.name}'. Waiting for member acceptance."},
                                status=status.HTTP_400_BAD_REQUEST
                            )

                        invitation = GroupInvitation.objects.create(
                            group=group,
                            member=member,
                            invited_by=request.user,
                            status=GroupInvitation.STATUS_PENDING
                        )
                        invitation_id = invitation.id

                    return Response({
                        "message": "Group invitation sent to member. They will be enrolled once they accept.",
                        "is_invitation": True,
                        "invitation_id": invitation_id,
                        "username": user.username,
                        "member_id": member.id,
                        "member_name": member.name,
                        "phone": member.phone,
                        "group_id": group.id if group else None,
                        "group_name": group.name if group else "",
                        "monthly_amount": float(group.monthly_amount or 0) if group else 0.0,
                        "duration_months": group.duration_months or 20 if group else 20
                    }, status=status.HTTP_201_CREATED)

                else:
                    # Fresh User Registration -> Direct Enrollment with Token
                    if not phone or not phone.isdigit() or len(phone) < 10:
                        return Response(
                            {"detail": "A valid 10-digit mobile number is required."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    if Member.objects.filter(phone=phone).exists() or User.objects.filter(username=phone).exists():
                        return Response(
                            {"detail": f"Mobile number '{phone}' is already registered. Please tap Auto-Fill to enrol this member."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    if email and (Member.objects.filter(email__iexact=email).exists() or User.objects.filter(email__iexact=email).exists()):
                        return Response(
                            {"detail": f"Email '{email}' is already registered. Please tap Auto-Fill to enrol this member."},
                            status=status.HTTP_400_BAD_REQUEST
                        )

                    username = phone
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

                    # 🎟️ Safe Token Creation in ChittiMember for Fresh Registration
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
                        "message": "New member registered and enrolled successfully",
                        "is_invitation": False,
                        "username": user.username,
                        "member_id": member.id,
                        "member_name": member.name,
                        "phone": member.phone,
                        "group_id": group.id if group else None,
                        "group_name": group.name if group else "",
                        "monthly_amount": float(group.monthly_amount or 0) if group else 0.0,
                        "duration_months": group.duration_months or 20 if group else 20
                    }, status=status.HTTP_201_CREATED)

        except IntegrityError as ie:
            return Response(
                {"detail": "A member with this mobile number or email already exists in the system."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {"detail": f"Failed to enrol member: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

# MEMBER UPDATE (Group Admin)
class MemberUpdateAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def put(self, request, pk):
        admin_groups = ChittiGroup.objects.filter(owner=request.user)
        member = Member.objects.filter(
            Q(pk=pk),
            Q(assigned_chitti_group__in=admin_groups) |
            Q(chitti_memberships__group__in=admin_groups)
        ).distinct().first()

        if not member:
            return Response(
                {"detail": "Member not found in your groups or permission denied."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Allowed fields only
        allowed_fields = ["name", "email", "phone", "address", "aadhaar_no"]

        data = {}
        for field in allowed_fields:
            if field in request.data:
                data[field] = request.data[field]

        serializer = MemberSerializer(member, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_member = serializer.save()

        # 🔄 Sync Auth User model (username, email, name) across entire system
        if updated_member.user:
            user_changed = False
            new_phone = data.get("phone", "").strip()
            new_email = data.get("email", "").strip()
            new_name = data.get("name", "").strip()

            if new_phone and updated_member.user.username != new_phone:
                # Check collision with another user
                if not User.objects.filter(username=new_phone).exclude(id=updated_member.user.id).exists():
                    updated_member.user.username = new_phone
                    user_changed = True

            if new_email and updated_member.user.email != new_email:
                if not User.objects.filter(email__iexact=new_email).exclude(id=updated_member.user.id).exists():
                    updated_member.user.email = new_email
                    user_changed = True

            if new_name:
                updated_member.user.first_name = new_name
                user_changed = True

            if user_changed:
                updated_member.user.save()

        return Response({"message": "Member updated successfully"})
    

# MEMBER DELETE (Group Admin)
class MemberDeleteAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        # 1. Try finding by Member.id or ChittiMember.id
        member = Member.objects.filter(pk=pk).first()
        if not member:
            cm = ChittiMember.objects.filter(pk=pk).first()
            if cm:
                member = cm.member

        if not member:
            return Response(
                {"detail": "No member found with the given ID."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Check ownership/permission
        admin_groups = ChittiGroup.objects.filter(owner=request.user)
        admin_memberships = ChittiMember.objects.filter(group__in=admin_groups, member=member)
        admin_invitations = GroupInvitation.objects.filter(group__in=admin_groups, member=member)
        is_assigned = member.assigned_chitti_group and member.assigned_chitti_group.owner == request.user

        if not (admin_memberships.exists() or admin_invitations.exists() or is_assigned or request.user.is_staff or request.user.is_superuser):
            return Response(
                {"detail": "You do not have permission to delete this member."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 3. Check if member already won an auction in this group
        if admin_memberships.filter(won_auctions__isnull=False).exists():
            return Response(
                {"detail": "Cannot delete member: This member has already won an auction in this group."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4. Remove memberships and invitations for this admin's groups
        with transaction.atomic():
            admin_memberships.delete()
            admin_invitations.delete()

            if is_assigned:
                member.assigned_chitti_group = None
                member.save(update_fields=["assigned_chitti_group"])

            # 5. If this member is not enrolled in any other groups across the platform,
            # safely clean up the Member record and their user profile.
            other_memberships = ChittiMember.objects.filter(member=member).exists()
            if not other_memberships:
                auth_user = member.user
                member.delete()
                if auth_user and not auth_user.is_staff and not auth_user.is_superuser:
                    if not ChittiGroup.objects.filter(owner=auth_user).exists():
                        auth_user.delete()

        return Response({"message": "Member deleted successfully"})
    


class MemberDetailAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        group_id = request.GET.get("group_id")

        cm_qs = ChittiMember.objects.filter(
            member__id=pk,
            group__owner=request.user
        ).select_related("member", "group")

        if group_id:
            try:
                cm_qs = cm_qs.filter(group_id=int(group_id))
            except (ValueError, TypeError):
                pass

        member_record = cm_qs.first()

        if not member_record:
            # Fallback: check if member has assigned_chitti_group owned by request.user
            m = Member.objects.filter(id=pk).first()
            if m and m.assigned_chitti_group and m.assigned_chitti_group.owner == request.user:
                if not group_id or str(m.assigned_chitti_group_id) == str(group_id):
                    member_record, _ = ChittiMember.objects.get_or_create(
                        member=m,
                        group=m.assigned_chitti_group,
                        defaults={"token_no": 1}
                    )

        if not member_record:
            return Response(
                {"detail": "Member not found in your groups."},
                status=status.HTTP_404_NOT_FOUND
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
                "id": member.id,
                "chitti_member_id": member_record.id,
                "token_no": member_record.token_no,
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
            cm_filters = Q(member__user=user) | Q(member__in=Member.objects.filter(user_filters))
            if user.email:
                cm_filters |= Q(member__email=user.email)
            if user.username:
                cm_filters |= Q(member__phone=user.username)
            cm = ChittiMember.objects.filter(cm_filters, group_id=gid).select_related('member', 'group').first()
            if cm:
                return cm.member

            # 3. Match by phone or email directly for this group
            ident_filters = Q()
            if user.username:
                ident_filters |= Q(phone=user.username)
            if user.email:
                ident_filters |= Q(email=user.email)
            if ident_filters:
                m_direct = Member.objects.filter(ident_filters, assigned_chitti_group_id=gid).select_related('assigned_chitti_group').first()
                if m_direct:
                    return m_direct
                cm_direct = ChittiMember.objects.filter(Q(member__phone=user.username) if user.username else Q(), group_id=gid).select_related('member', 'group').first()
                if cm_direct:
                    return cm_direct.member
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
        user = request.user
        group_id = request.GET.get('group_id') or request.GET.get('group')
        member = get_member_for_user(request, group_id=group_id)

        user_filters = Q(user=user)
        if user.email:
            user_filters |= Q(email__iexact=user.email)
        if user.username:
            user_filters |= Q(phone=user.username)
        all_user_members = Member.objects.filter(user_filters)

        if not member and all_user_members.exists():
            member = all_user_members.first()

        # Query all pending invitations across any member profile for this user
        pending_invs = GroupInvitation.objects.filter(
            member__in=all_user_members,
            status=GroupInvitation.STATUS_PENDING,
            group__is_active=True
        ).select_related("group", "invited_by", "member").order_by("-created_at")

        inv_data = []
        for inv in pending_invs:
            admin_name = inv.invited_by.get_full_name() or inv.invited_by.username if inv.invited_by else "Group Admin"
            g_monthly = float(inv.group.monthly_amount or 0)
            g_dur = int(inv.group.duration_months or 20)
            inv_data.append({
                "id": inv.id,
                "phone": inv.member.phone if inv.member else "",
                "member_name": inv.member.name if inv.member else "",
                "group_id": inv.group.id,
                "group_name": inv.group.name,
                "admin_name": admin_name,
                "monthly_amount": g_monthly,
                "duration_months": g_dur,
                "total_amount": float(inv.group.total_amount or (g_monthly * g_dur)),
                "status": inv.status,
                "created_at": inv.created_at.isoformat(),
            })

        if not member:
            return Response({
                "member": {
                    "id": 0,
                    "name": user.get_full_name() or user.username,
                    "phone": user.username if user.username.isdigit() else "",
                    "email": user.email or "",
                    "is_active": True,
                    "group_id": 0,
                    "group_name": "No Active Kuri",
                    "address": "",
                    "join_date": "",
                    "aadhaar_masked": None,
                },
                "total_paid": 0.0,
                "total_amount": 0.0,
                "remaining": 0.0,
                "auctions": [],
                "latest_auction": None,
                "is_winner": False,
                "pending_invitations": inv_data,
            })

        # Resolve active group: prefer group_id if requested, else member's group or ChittiMember
        group = None
        if group_id:
            try:
                group = ChittiGroup.objects.filter(id=int(group_id), is_active=True).first()
            except (ValueError, TypeError):
                pass

        if not group:
            group = member.assigned_chitti_group
            if not group or not group.is_active:
                cm = ChittiMember.objects.filter(member=member, group__is_active=True).select_related('group').first()
                if cm:
                    group = cm.group

        token_no = None
        monthly_amount = float(group.monthly_amount or 0) if group else 0.0
        duration_months = int(group.duration_months or 20) if group else 0
        current_month = group.current_month if group else 1
        paid_count = 0
        group_code = group.code if group else ""
        start_date = group.start_date.isoformat() if (group and group.start_date) else ""
        collector_name = (group.collector.user.get_full_name() or group.collector.user.username) if (group and group.collector and group.collector.user) else ""
        collector_phone = group.collector.phone if (group and group.collector) else ""
        owner_name = (group.owner.get_full_name() or group.owner.username) if (group and group.owner) else "Group Admin"
        owner_phone = (group.phone or (group.owner.username if (group.owner and group.owner.username.isdigit()) else "")) if (group and group.owner) else ""

        if group:
            payments = Payment.objects.filter(member=member, group=group, payment_status="success")
            total_paid = float(payments.aggregate(total=Sum('amount'))['total'] or 0.0)
            total_amount = float(group.total_amount or ((group.monthly_amount or 0) * (group.duration_months or 20)))
            remaining = max(0.0, total_amount - total_paid)
            auctions = Auction.objects.filter(group=group, winner__isnull=False).order_by('auction_date')
            latest_auction = auctions.last()
            is_winner = auctions.filter(winner__member=member).exists()

            cm = ChittiMember.objects.filter(member=member, group=group).first()
            if cm:
                token_no = cm.token_no
            paid_count = payments.count()
        else:
            total_paid = 0.0
            total_amount = 0.0
            remaining = 0.0
            auctions = Auction.objects.none()
            latest_auction = None
            is_winner = False

        member_data = MemberSerializer(member).data
        if group:
            member_data['group_id'] = group.id
            member_data['group_name'] = group.name
        else:
            member_data['group_id'] = 0
            member_data['group_name'] = "No Active Kuri"

        notes = []
        if group:
            notes.append({
                "title": "Payment Schedule Notice",
                "content": f"Monthly installment of ₹{int(monthly_amount):,} is due by the 10th of every month.",
                "type": "info",
                "tag": "SCHEDULE"
            })
            if is_winner:
                notes.append({
                    "title": "Prize Winner Guideline",
                    "content": "Congratulations on winning the auction! Please ensure timely payment of remaining installments to maintain your good standing.",
                    "type": "success",
                    "tag": "WINNER"
                })
            else:
                notes.append({
                    "title": "Auction Participation",
                    "content": "Bidding is open to all members with up-to-date installments. Check the Auctions tab for upcoming schedules.",
                    "type": "gold",
                    "tag": "AUCTION"
                })
            notes.append({
                "title": "Receipts & Verification",
                "content": "Always verify your digital receipts immediately upon payment from the History tab.",
                "type": "notice",
                "tag": "SAFETY"
            })

        return Response({
            "member": member_data,
            "total_paid": total_paid,
            "total_amount": total_amount,
            "remaining": remaining,
            "token_no": token_no,
            "monthly_amount": monthly_amount,
            "duration_months": duration_months,
            "current_month": current_month,
            "paid_count": paid_count,
            "group_code": group_code,
            "start_date": start_date,
            "admin_name": owner_name,
            "admin_phone": owner_phone,
            "collector_name": collector_name,
            "collector_phone": collector_phone,
            "notes": notes,
            "auctions": AuctionSerializer(auctions, many=True).data,
            "latest_auction": AuctionSerializer(latest_auction).data if latest_auction else None,
            "is_winner": is_winner,
            "pending_invitations": inv_data,
        })


# -----------------------------
# Member Profile
# -----------------------------
class MemberProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group_id = request.GET.get("group_id") or request.GET.get("group")
        member = get_member_for_user(request, group_id=group_id)
        if not member:
            return Response({
                "id": 0,
                "name": request.user.get_full_name() or request.user.username,
                "email": request.user.email or "",
                "phone": request.user.username if request.user.username.isdigit() else "",
                "address": "",
                "aadhaar_no": "",
                "assigned_chitti_group_name": "None",
                "group_name": "None",
                "group_id": 0
            })

        group = None
        if group_id:
            try:
                group = ChittiGroup.objects.filter(id=int(group_id), is_active=True).first()
            except (ValueError, TypeError):
                pass
        if not group:
            group = member.assigned_chitti_group
            if not group or not group.is_active:
                cm = ChittiMember.objects.filter(member=member, group__is_active=True).select_related('group').first()
                if cm:
                    group = cm.group

        data = MemberSerializer(member, context={"request": request, "group_id": group_id, "group": group}).data
        if group:
            data['group_id'] = group.id
            data['group_name'] = group.name
            data['monthly_amount'] = float(group.monthly_amount or 0)
        return Response(data)

    def patch(self, request):
        group_id = request.GET.get("group_id") or request.GET.get("group")
        member = get_member_for_user(request, group_id=group_id)
        if not member:
            return Response({"error": "Member profile not found"}, status=status.HTTP_404_NOT_FOUND)

        updated_fields = []

        if "aadhaar_no" in request.data or "aadhaar" in request.data:
            aadhaar_no = (request.data.get("aadhaar_no") or request.data.get("aadhaar") or "").strip()
            clean_aadhaar = aadhaar_no.replace(" ", "").replace("-", "")
            if len(clean_aadhaar) != 12 or not clean_aadhaar.isdigit():
                return Response({"error": "Please enter a valid 12-digit Aadhaar number"}, status=status.HTTP_400_BAD_REQUEST)
            member.aadhaar_no = clean_aadhaar
            updated_fields.append("aadhaar_no")

        if "address" in request.data:
            address = (request.data.get("address") or "").strip()
            member.address = address
            updated_fields.append("address")

        if not updated_fields:
            return Response({"error": "No valid fields provided for update"}, status=status.HTTP_400_BAD_REQUEST)

        member.save(update_fields=updated_fields)

        clean_aadhaar = member.aadhaar_no or ""
        masked = ("XXXX-XXXX-" + clean_aadhaar[-4:]) if clean_aadhaar else None

        return Response({
            "message": "Profile updated successfully",
            "aadhaar_masked": masked,
            "member": MemberSerializer(member).data
        }, status=status.HTTP_200_OK)


# -----------------------------
# Member Payment History
# -----------------------------
class MemberPaymentsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        group_id = request.GET.get("group_id") or request.GET.get("group")
        member = get_member_for_user(request, group_id=group_id)
        if not member:
            return Response({
                "group": {"id": 0, "name": "No Active Group", "monthly_amount": 0, "duration": 0, "current_month": 1},
                "summary": {"total_paid": 0, "total_due": 0, "collections_paid": 0},
                "payment_rows": []
            }, status=status.HTTP_200_OK)

        # ✅ Group
        group = None
        if group_id:
            try:
                group = ChittiGroup.objects.filter(id=int(group_id), is_active=True).first()
            except (ValueError, TypeError):
                pass

        if not group:
            member_record = (
                ChittiMember.objects
                .filter(member=member, group__is_active=True)
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
        group_id = request.GET.get('group_id') or request.GET.get('group')
        member = get_member_for_user(request, group_id=group_id)
        if not member:
            return Response({
                "member": {"id": 0, "name": request.user.username},
                "group": {"id": 0, "name": "No Active Group", "duration_months": 20, "current_month": 1, "monthly_amount": 0.0, "total_amount": 0.0},
                "today": timezone.now().date(),
                "auctions": [],
                "stats": {"total_auctions": 0, "completed_auctions": 0, "pending_auctions": 0}
            }, status=status.HTTP_200_OK)

        group = None
        if group_id:
            try:
                group = ChittiGroup.objects.filter(id=int(group_id), is_active=True).first()
            except (ValueError, TypeError):
                pass
        if not group:
            group = member.assigned_chitti_group

        if not group:
            return Response({
                "member": {"id": member.id, "name": member.name},
                "group": {"id": 0, "name": "No Active Group", "duration_months": 20, "current_month": 1, "monthly_amount": 0.0, "total_amount": 0.0},
                "today": timezone.now().date(),
                "auctions": [],
                "stats": {"total_auctions": 0, "completed_auctions": 0, "pending_auctions": 0}
            }, status=status.HTTP_200_OK)

        auctions_qs = (
            Auction.objects
            .filter(group=group)
            .select_related('group', 'winner__member__user')
            .order_by('month_no', 'auction_date')
        )

        return Response({
            "member": {
                "id": member.id,
                "name": member.name,
            },
            "group": {
                "id": group.id,
                "name": group.name,
                "duration_months": group.duration_months or 20,
                "current_month": group.current_month or 1,
                "monthly_amount": float(group.monthly_amount or 0),
                "total_amount": float(group.total_amount or 0),
            },
            "today": timezone.now().date(),
            "auctions": AuctionSerializer(auctions_qs, many=True).data,
            "stats": {
                "total_auctions": auctions_qs.count(),
                "completed_auctions": auctions_qs.filter(winner__isnull=False).count(),
                "pending_auctions": auctions_qs.filter(winner__isnull=True).count(),
            }
        }, status=status.HTTP_200_OK)


# -----------------------------
# Member Group Invitations & Consent
# -----------------------------
class MemberInvitationsAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_filters = Q(user=user)
        if user.email:
            user_filters |= Q(email__iexact=user.email)
        if user.username:
            user_filters |= Q(phone=user.username)
        user_members = Member.objects.filter(user_filters)

        invitations = GroupInvitation.objects.filter(
            member__in=user_members,
            status=GroupInvitation.STATUS_PENDING,
            group__is_active=True
        ).select_related("group", "invited_by", "member").order_by("-created_at")

        data = []
        for inv in invitations:
            g = inv.group
            admin_name = inv.invited_by.get_full_name() or inv.invited_by.username if inv.invited_by else "Group Admin"
            g_monthly = float(g.monthly_amount or 0)
            g_dur = int(g.duration_months or 20)
            data.append({
                "id": inv.id,
                "phone": inv.member.phone if inv.member else "",
                "member_name": inv.member.name if inv.member else "",
                "group_id": g.id,
                "group_name": g.name,
                "admin_name": admin_name,
                "monthly_amount": g_monthly,
                "duration_months": g_dur,
                "total_amount": float(g.total_amount or (g_monthly * g_dur)),
                "status": inv.status,
                "created_at": inv.created_at.isoformat(),
            })

        return Response({"invitations": data}, status=status.HTTP_200_OK)


class MemberInvitationRespondAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        user = request.user
        user_filters = Q(user=user)
        if user.email:
            user_filters |= Q(email__iexact=user.email)
        if user.username:
            user_filters |= Q(phone=user.username)
        user_members = Member.objects.filter(user_filters)

        invitation = get_object_or_404(
            GroupInvitation,
            pk=pk,
            member__in=user_members,
            status=GroupInvitation.STATUS_PENDING
        )
        member = invitation.member
        group = invitation.group

        action = (request.data.get("action") or "").lower().strip()
        if action not in ["accept", "decline"]:
            return Response({"detail": "Invalid action. Use 'accept' or 'decline'."}, status=status.HTTP_400_BAD_REQUEST)

        if action == "accept":
            if not can_add_member(group):
                return Response(
                    {"detail": f"Cannot join '{group.name}': Group limit reached or subscription expired."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if somehow already enrolled
            if ChittiMember.objects.filter(group=group, member=member).exists():
                invitation.status = GroupInvitation.STATUS_ACCEPTED
                invitation.save()
                return Response({
                    "message": f"You are already enrolled in '{group.name}'.",
                    "group_id": group.id,
                    "group_name": group.name
                }, status=status.HTTP_200_OK)

            with transaction.atomic():
                last_token = ChittiMember.objects.filter(group=group).aggregate(
                    max_token=Max("token_no")
                )["max_token"] or 0
                next_token = last_token + 1

                ChittiMember.objects.create(
                    group=group,
                    member=member,
                    token_no=next_token
                )
                if not member.assigned_chitti_group:
                    member.assigned_chitti_group = group
                    member.save(update_fields=['assigned_chitti_group'])

                invitation.status = GroupInvitation.STATUS_ACCEPTED
                invitation.save()

            return Response({
                "message": f"Welcome to '{group.name}'! Your ticket number is #{next_token}.",
                "token_no": next_token,
                "group_id": group.id,
                "group_name": group.name
            }, status=status.HTTP_200_OK)

        elif action == "decline":
            invitation.status = GroupInvitation.STATUS_DECLINED
            invitation.save()
            return Response({
                "message": f"Invitation for '{group.name}' has been declined."
            }, status=status.HTTP_200_OK)