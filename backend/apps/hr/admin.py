from django.contrib import admin

from .models import Attendance, Department, Employee, LeaveRequest, StaffShift


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "organization"]


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["employee_number", "first_name", "last_name", "branch", "job_title", "status"]
    list_filter = ["branch", "status", "department"]
    search_fields = ["first_name", "last_name", "employee_number"]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["employee", "date", "clock_in", "clock_out", "branch"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ["employee", "leave_type", "start_date", "end_date", "status"]
    list_filter = ["status", "leave_type"]


@admin.register(StaffShift)
class StaffShiftAdmin(admin.ModelAdmin):
    list_display = ["employee", "branch", "starts_at", "ends_at"]
