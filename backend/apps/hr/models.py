from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Branch, Organization, TimeStamped


class Department(TimeStamped):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name


class Employee(TimeStamped):
    EMPLOYMENT = [("permanent", "Permanent"), ("contract", "Contract"), ("casual", "Casual"), ("intern", "Intern")]
    STATUS = [("active", "Active"), ("suspended", "Suspended"), ("terminated", "Terminated")]
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="employees")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, null=True, blank=True, related_name="employees",
                               help_text="Empty for head-office staff.")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="employee", help_text="System login, if the person uses the system.")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    employee_number = models.CharField(max_length=30)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    national_id = models.CharField(max_length=40, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    employment_type = models.CharField(max_length=10, choices=EMPLOYMENT, default="permanent")
    status = models.CharField(max_length=10, choices=STATUS, default="active")
    hire_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    basic_salary = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    annual_leave_days = models.PositiveSmallIntegerField(default=18)
    next_of_kin = models.CharField(max_length=200, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField(max_length=40, blank=True)

    class Meta:
        unique_together = [("organization", "employee_number")]
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.employee_number} {self.first_name} {self.last_name}"


class Attendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    date = models.DateField(db_index=True)
    clock_in = models.DateTimeField()
    clock_out = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("employee", "date")]
        ordering = ["-date"]


class LeaveRequest(TimeStamped):
    TYPES = [("annual", "Annual"), ("sick", "Sick"), ("maternity", "Maternity"), ("paternity", "Paternity"),
             ("compassionate", "Compassionate"), ("unpaid", "Unpaid")]
    STATUS = [("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.CharField(max_length=15, choices=TYPES)
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.DecimalField(max_digits=5, decimal_places=1)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("End date is before start date.")


class StaffShift(models.Model):
    """Rota: who is scheduled at which branch and when."""

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shifts")
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    role_note = models.CharField(max_length=100, blank=True, help_text="e.g. Till 2, Stores")

    class Meta:
        ordering = ["starts_at"]
