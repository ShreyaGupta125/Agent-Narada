import os

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import Action, CanApproveDocuments, CanUploadDocuments, user_can

from .models import Document, DocumentStatus
from .processing import IngestionError, process_document
from .serializers import DocumentAccessSerializer, DocumentUploadSerializer

ACCESS_LABELS = [
    ("for_students", "Students"),
    ("for_teaching_staff", "Teaching staff"),
    ("for_non_teaching_staff", "Non-teaching staff"),
]


def documents_for(user):
    """The documents this user may see and manage.

    Super Admin (who may approve): every document.
    Admin: only the documents they uploaded themselves.

    Every view below starts from this, so an Admin asking for another
    Admin's document gets "404 Not Found", as if it did not exist.
    """
    documents = Document.objects.select_related("uploaded_by", "reviewed_by")
    if user_can(user, Action.APPROVE_DOCUMENT):
        return documents
    return documents.filter(uploaded_by=user)


def can_change(user, document):
    """Who may delete a document or change who may read it.

    Super Admin: any document. Admin: their own, unless it is approved.
    An approved document is part of the knowledge base, so removing it
    or changing its readers is the Super Admin's decision."""
    if user_can(user, Action.APPROVE_DOCUMENT):
        return True
    return document.uploaded_by_id == user.pk and document.status != DocumentStatus.APPROVED


def document_row(document, viewer):
    """One document as shown in the browser."""
    return {
        "id": document.pk,
        "title": document.title,
        "description": document.description,
        "filename": os.path.basename(document.file.name),
        "access": [label for field, label in ACCESS_LABELS if getattr(document, field)],
        "status": document.status,
        "status_label": document.get_status_display(),
        "uploaded_by": document.uploaded_by.username if document.uploaded_by else None,
        "uploaded_at": document.uploaded_at.isoformat(),
        "reviewed_by": document.reviewed_by.username if document.reviewed_by else None,
        "reviewed_at": document.reviewed_at.isoformat() if document.reviewed_at else None,
        "rejection_reason": document.rejection_reason,
        "passage_count": document.passage_count,
        "processed": document.is_processed,
        "file_url": f"/api/documents/{document.pk}/file/",
        "can_delete": can_change(viewer, document),
        "can_change_access": can_change(viewer, document),
    }


class DocumentListView(APIView):
    """Admin and Super Admin.

    GET  /api/documents/            -> the documents this user may see
    GET  /api/documents/?status=PENDING   (or APPROVED, REJECTED)
    POST /api/documents/            -> upload a document
    """

    permission_classes = [CanUploadDocuments]

    def get(self, request):
        documents = documents_for(request.user)
        wanted = request.query_params.get("status")
        if wanted in DocumentStatus.values:
            documents = documents.filter(status=wanted)
        return Response([document_row(document, request.user) for document in documents])

    def post(self, request):
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        document = None
        try:
            # atomic(): the document and its passages are stored together,
            # or not at all. If the text cannot be read, the database is
            # left exactly as it was.
            with transaction.atomic():
                # The uploader is the logged-in user, never a value from
                # the form. The model then sets the status: PENDING for an
                # Admin, APPROVED for a Super Admin.
                document = serializer.save(uploaded_by=request.user)

                # Extract the text, split it into passages, index them.
                # A pending document is processed too, but its passages
                # stay out of every search until it is approved.
                process_document(document)
        except IngestionError as error:
            # Nothing was kept in the database; remove the saved file too,
            # and tell the administrator why.
            if document is not None:
                document.file.delete(save=False)
            return Response(
                {"file": [f"The document was not uploaded: {error}"]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(document_row(document, request.user), status=status.HTTP_201_CREATED)


class DocumentDetailView(APIView):
    """PATCH  /api/documents/<id>/  -> change who may read it, with
               {"for_students": true, "for_teaching_staff": true,
                "for_non_teaching_staff": false}
    DELETE /api/documents/<id>/  -> remove a document and its file.
    """

    permission_classes = [CanUploadDocuments]

    def patch(self, request, document_id):
        document = get_object_or_404(documents_for(request.user), pk=document_id)
        if not can_change(request.user, document):
            return Response(
                {"detail": "Who may read an approved document can only be changed by the Super Admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = DocumentAccessSerializer(document, data=request.data)
        serializer.is_valid(raise_exception=True)
        # Only the three access fields are saved. The status, the file and
        # the passages stay as they are, and the next question already
        # searches with the new readers.
        serializer.save()
        return Response(document_row(document, request.user))

    def delete(self, request, document_id):
        document = get_object_or_404(documents_for(request.user), pk=document_id)
        if not can_change(request.user, document):
            return Response(
                {"detail": "An approved document can only be removed by the Super Admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        document.file.delete(save=False)  # remove the file from the media folder
        document.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentFileView(APIView):
    """GET /api/documents/<id>/file/  -> download the uploaded file.

    The media folder has no web address. This view is the only way to
    reach a file, and it checks the role and the ownership first.
    """

    permission_classes = [CanUploadDocuments]

    def get(self, request, document_id):
        document = get_object_or_404(documents_for(request.user), pk=document_id)
        return FileResponse(
            document.file.open("rb"),
            as_attachment=True,
            filename=os.path.basename(document.file.name),
        )


class DocumentApproveView(APIView):
    """POST /api/documents/<id>/approve/  -> Super Admin only."""

    permission_classes = [CanApproveDocuments]

    def post(self, request, document_id):
        document = get_object_or_404(documents_for(request.user), pk=document_id)
        try:
            document.approve(request.user)
        except ValidationError as error:
            # The model refuses to approve a document whose text was not read.
            return Response({"detail": error.messages[0]}, status=status.HTTP_400_BAD_REQUEST)
        return Response(document_row(document, request.user))


class DocumentRejectView(APIView):
    """POST /api/documents/<id>/reject/  with {"reason": "..."}  -> Super Admin only."""

    permission_classes = [CanApproveDocuments]

    def post(self, request, document_id):
        document = get_object_or_404(documents_for(request.user), pk=document_id)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            document.reject(request.user, data.get("reason"))
        except ValidationError as error:
            # The model refuses a rejection without a reason.
            return Response({"reason": error.messages}, status=status.HTTP_400_BAD_REQUEST)
        return Response(document_row(document, request.user))
