"""Shared list filters."""
from django.db import models
from django.utils.dateparse import parse_date
from rest_framework.filters import BaseFilterBackend


class DateRangeFilter(BaseFilterBackend):
    """?from=YYYY-MM-DD&to=YYYY-MM-DD on every list. Uses the view's `date_field`, else the model's
    `date` field if it has one, else `created_at`."""

    def filter_queryset(self, request, queryset, view):
        start, end = parse_date(request.query_params.get("from") or ""), parse_date(request.query_params.get("to") or "")
        if not (start or end) or not hasattr(queryset, "model"):
            return queryset
        names = {f.name: f for f in queryset.model._meta.get_fields() if hasattr(f, "get_internal_type")}
        field = getattr(view, "date_field", None) or ("date" if "date" in names else "created_at")
        if field not in names:
            return queryset
        lookup = field + ("__date" if isinstance(names[field], models.DateTimeField) else "")
        if start:
            queryset = queryset.filter(**{f"{lookup}__gte": start})
        if end:
            queryset = queryset.filter(**{f"{lookup}__lte": end})
        return queryset
