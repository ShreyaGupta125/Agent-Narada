from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, User
from accounts.permissions import CanOpenAdminDashboard, CanOpenSuperAdminDashboard
from documents.models import Document, DocumentStatus

# The numbers shown on the two dashboards. Each endpoint is open to one
# role only; every other role receives 403 Forbidden.


def count_by(queryset, field):
    """Count the rows for each value of a field, in one database query.
    Example result: {"STUDENT": 40, "ADMIN": 2}"""
    return dict(queryset.values_list(field).annotate(total=Count("pk")))


def document_counts(documents):
    """Documents in total and in each approval status."""
    by_status = count_by(documents, "status")
    return {
        "total": sum(by_status.values()),
        "pending": by_status.get(DocumentStatus.PENDING, 0),
        "approved": by_status.get(DocumentStatus.APPROVED, 0),
        "rejected": by_status.get(DocumentStatus.REJECTED, 0),
    }


class SuperAdminDashboardView(APIView):
    """GET /api/dashboard/super-admin/  -> system-wide totals."""

    permission_classes = [CanOpenSuperAdminDashboard]

    def get(self, request):
        by_role = count_by(User.objects.all(), "role")
        return Response(
            {
                "users": {
                    "total": sum(by_role.values()),
                    "students": by_role.get(Role.STUDENT, 0),
                    "teaching_staff": by_role.get(Role.TEACHING_STAFF, 0),
                    "non_teaching_staff": by_role.get(Role.NON_TEACHING_STAFF, 0),
                    "admins": by_role.get(Role.ADMIN, 0),
                    "super_admins": by_role.get(Role.SUPER_ADMIN, 0),
                },
                "documents": document_counts(Document.objects.all()),
            }
        )


class AdminDashboardView(APIView):
    """GET /api/dashboard/admin/  -> totals for this Admin's own uploads."""

    permission_classes = [CanOpenAdminDashboard]

    def get(self, request):
        # Only the documents this Admin uploaded, never another Admin's.
        own_documents = Document.objects.filter(uploaded_by=request.user)
        return Response({"documents": document_counts(own_documents)})
