from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api import OrgScopedViewSet, PermCodeMixin, branches_with, require_perm
from apps.accounts.models import User
from apps.core.models import audit, next_number
from rest_framework import viewsets

from .models import Attendance, Department, Employee, LeaveRequest, StaffShift


def hr_scope(user, code):
    """Q filter on Employee for what this user may see/manage: org-wide HR sees all (incl. head office),
    branch HR only their branches' staff."""
    if user.has_org_perm(code):
        return Q(organization=user.organization)
    return Q(branch__in=[b.pk for b in branches_with(user, code)])


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        exclude = ["organization"]


SENSITIVE = ("national_id", "basic_salary", "bank_name", "bank_account", "next_of_kin")


def can_manage(user, emp):
    return user.has_org_perm("hr.manage") or (emp.branch_id is not None and user.has_branch_perm(emp.branch, "hr.manage"))


class EmployeeSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source="branch.name", read_only=True, default="")
    department_name = serializers.CharField(source="department.name", read_only=True, default="")
    username = serializers.CharField(source="user.username", read_only=True, default="")
    login_active = serializers.BooleanField(source="user.is_active", read_only=True, default=None)

    class Meta:
        model = Employee
        exclude = ["organization"]
        extra_kwargs = {"employee_number": {"required": False, "allow_blank": True}}

    def to_representation(self, emp):
        data = super().to_representation(emp)
        # Pay, bank and ID details only for people who manage this employee (not branch admins with hr.view).
        data["can_manage"] = can_manage(self.context["request"].user, emp)
        if not data["can_manage"]:
            for f in SENSITIVE:
                data.pop(f, None)
        return data

    def validate_employee_number(self, value):
        value = (value or "").strip().upper()
        if value:
            qs = Employee.objects.filter(organization=self.context["request"].user.organization,
                                         employee_number__iexact=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError(f"Already used by {qs.first().first_name} {qs.first().last_name}.")
        return value

    def validate(self, attrs):
        org = self.context["request"].user.organization
        for f in ("branch", "department"):
            if attrs.get(f) and attrs[f].organization_id != org.pk:
                raise serializers.ValidationError({f: "Not found."})
        user = attrs.get("user")
        if user:
            if user.organization_id != org.pk:
                raise serializers.ValidationError({"user": "Not found."})
            other = Employee.objects.filter(user=user).exclude(pk=getattr(self.instance, "pk", None)).first()
            if other:
                raise serializers.ValidationError({"user": f"Login already linked to {other.first_name} {other.last_name}."})

        def get(k):
            return attrs.get(k, getattr(self.instance, k, None))

        if get("status") == "terminated" and not get("end_date"):
            raise serializers.ValidationError({"end_date": "Give the last working day."})
        if get("end_date") and get("hire_date") and get("end_date") < get("hire_date"):
            raise serializers.ValidationError({"end_date": "Cannot be before the hire date."})
        if get("basic_salary") is not None and get("basic_salary") < 0:
            raise serializers.ValidationError({"basic_salary": "Cannot be negative."})
        return attrs


class AttendanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attendance
        fields = "__all__"


class LeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.__str__", read_only=True)

    class Meta:
        model = LeaveRequest
        fields = "__all__"
        read_only_fields = ["status", "decided_by", "decided_at"]


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffShift
        fields = "__all__"


class DepartmentViewSet(OrgScopedViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    write_perm = "hr.manage"


class EmployeeViewSet(PermCodeMixin, viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    search_fields = ["first_name", "last_name", "employee_number", "phone"]
    filterset_fields = ["branch", "department", "status"]

    def get_queryset(self):
        code = "hr.view" if self.request.method == "GET" else "hr.manage"
        return Employee.objects.filter(hr_scope(self.request.user, code)).select_related("branch", "department")

    def _check(self, branch):
        u = self.request.user
        if u.has_org_perm("hr.manage"):
            return
        if branch is None:
            raise PermissionDenied("Only organization HR manages head-office staff.")
        require_perm(u, branch, "hr.manage")

    def perform_create(self, serializer):
        self._check(serializer.validated_data.get("branch"))
        org = self.request.user.organization
        number = serializer.validated_data.get("employee_number")
        with transaction.atomic():
            while not number or Employee.objects.filter(organization=org, employee_number=number).exists():
                number = next_number(f"emp:{org.pk}", "E", 4)
            e = serializer.save(organization=org, employee_number=number)
        audit("hr.employee_created", organization=e.organization, branch=e.branch, actor=self.request.user, obj=e)
        self._offboard(e, was="")

    def perform_update(self, serializer):
        self._check(serializer.instance.branch)
        if "branch" in serializer.validated_data:
            self._check(serializer.validated_data["branch"])
        was = serializer.instance.status
        changed = {f: [str(getattr(serializer.instance, f)), str(v)] for f, v in serializer.validated_data.items()
                   if f in ("status", "branch", "basic_salary", "job_title") and getattr(serializer.instance, f) != v}
        e = serializer.save()
        if changed:
            audit("hr.employee_updated", organization=e.organization, branch=e.branch, actor=self.request.user,
                  obj=e, **changed)
        self._offboard(e, was)

    def _offboard(self, e, was):
        """Leaving staff lose system access the moment they are terminated."""
        if e.status == "terminated" and was != "terminated" and e.user_id and e.user.is_active:
            e.user.is_active = False
            e.user.save(update_fields=["is_active"])
            audit("user.deactivated", organization=e.organization, branch=e.branch, actor=self.request.user,
                  obj=e.user, reason="employee terminated", employee=e.employee_number)

    @action(detail=False)
    def linkable_users(self, request):
        """Logins in this organization not yet tied to an employee record (for the link dropdown)."""
        u = request.user
        if not (u.has_org_perm("hr.manage") or branches_with(u, "hr.manage")):
            raise PermissionDenied("HR managers only.")
        users = (User.objects.filter(organization=u.organization, employee__isnull=True, is_active=True)
                 .order_by("username").values("id", "username", "first_name", "last_name"))
        return Response(list(users))

    def perform_destroy(self, instance):
        raise PermissionDenied("Terminate employees (status) instead of deleting records.")


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    http_method_names = ["get", "post"]
    filterset_fields = ["employee", "date", "branch"]

    def get_queryset(self):
        u = self.request.user
        visible = Employee.objects.filter(hr_scope(u, "hr.view")).values("pk")
        return Attendance.objects.filter(Q(employee__in=visible) | Q(employee__user=u))

    def create(self, request, *args, **kwargs):
        raise ValidationError("Use clock_in / clock_out.")

    @action(detail=False, methods=["post"])
    def clock_in(self, request):
        emp = getattr(request.user, "employee", None)
        if not emp or not emp.branch_id:
            raise ValidationError("Your login is not linked to a branch employee record.")
        att, created = Attendance.objects.get_or_create(
            employee=emp, date=timezone.localdate(), defaults={"branch": emp.branch, "clock_in": timezone.now()})
        if not created:
            raise ValidationError("Already clocked in today.")
        return Response(self.get_serializer(att).data, status=201)

    @action(detail=False, methods=["post"])
    def clock_out(self, request):
        att = Attendance.objects.filter(employee__user=request.user, date=timezone.localdate(),
                                        clock_out__isnull=True).first()
        if not att:
            raise ValidationError("Not clocked in.")
        att.clock_out = timezone.now()
        att.save(update_fields=["clock_out"])
        return Response(self.get_serializer(att).data)


class LeaveViewSet(viewsets.ModelViewSet):
    """Staff request their own leave; HR (branch or org) approves."""

    serializer_class = LeaveSerializer
    http_method_names = ["get", "post"]
    filterset_fields = ["status", "employee", "leave_type"]
    search_fields = ["employee__first_name", "employee__last_name", "reason"]
    ordering_fields = ["created_at", "start_date", "end_date", "status"]

    def get_queryset(self):
        u = self.request.user
        visible = Employee.objects.filter(hr_scope(u, "hr.view")).values("pk")
        return LeaveRequest.objects.filter(Q(employee__in=visible) | Q(employee__user=u)).select_related("employee")

    def perform_create(self, serializer):
        emp = serializer.validated_data["employee"]
        u = self.request.user
        own = emp.user_id == u.pk
        if not own and not Employee.objects.filter(hr_scope(u, "hr.manage"), pk=emp.pk).exists():
            raise PermissionDenied("You can only request leave for yourself.")
        serializer.save()

    def _decide(self, request, status):
        lr = self.get_object()
        if lr.status != "pending":
            raise ValidationError("Already decided.")
        if not Employee.objects.filter(hr_scope(request.user, "hr.approve_leave"), pk=lr.employee_id).exists():
            raise PermissionDenied("You cannot approve leave for this employee.")
        if lr.employee.user_id == request.user.pk:
            raise PermissionDenied("You cannot approve your own leave.")
        lr.status, lr.decided_by, lr.decided_at = status, request.user, timezone.now()
        lr.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
        return Response(self.get_serializer(lr).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, "approved")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, "rejected")


class ShiftViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftSerializer
    filterset_fields = ["employee", "branch"]

    def get_queryset(self):
        u = self.request.user
        visible = Employee.objects.filter(hr_scope(u, "hr.view")).values("pk")
        return StaffShift.objects.filter(Q(employee__in=visible) | Q(employee__user=u))

    def perform_create(self, serializer):
        if not self.request.user.has_org_perm("hr.manage"):
            require_perm(self.request.user, serializer.validated_data["branch"], "hr.manage")
        serializer.save()

    perform_update = perform_create

    def perform_destroy(self, instance):
        if not self.request.user.has_org_perm("hr.manage"):
            require_perm(self.request.user, instance.branch, "hr.manage")
        instance.delete()
