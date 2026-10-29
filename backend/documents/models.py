from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import Action, user_can

# The file types a document may be. Each one needs a reader in extraction.py.
ALLOWED_EXTENSIONS = ["pdf", "txt", "docx", "doc", "odt"]

NOT_PROCESSED = (
    "This document's text has not been read, so it cannot be approved. "
    "Delete it and upload it again."
)

# Which field decides whether a chatbot role may read a document.
# Super Admin and Admin are not here: they have no chatbot.
ROLE_ACCESS_FIELD = {
    Role.STUDENT: "for_students",
    Role.TEACHING_STAFF: "for_teaching_staff",
    Role.NON_TEACHING_STAFF: "for_non_teaching_staff",
}


class DocumentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class DocumentQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The documents this user's role may get answers from.

        This is the gate for role-based retrieval: a document reaches the
        language model only if it is APPROVED, its text has been read
        (processed), and it is open to the user's role. Anyone else
        (including a deactivated account) gets nothing.
        """
        field = ROLE_ACCESS_FIELD.get(user.role)
        if field is None or not user.is_active:
            return self.none()
        return self.filter(status=DocumentStatus.APPROVED, processed_at__isnull=False, **{field: True})


class Document(models.Model):
    """One university document and its place in the approval workflow."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    file = models.FileField(
        upload_to="documents/%Y/%m/",
        validators=[FileExtensionValidator(ALLOWED_EXTENSIONS)],
    )

    # Who may read it through the chatbot. All three off means no chatbot
    # user can get answers from this document.
    for_students = models.BooleanField(default=False)
    for_teaching_staff = models.BooleanField(default=False)
    for_non_teaching_staff = models.BooleanField(default=False)

    # Upload. SET_NULL: if the uploader's account is deleted later, the
    # document stays.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="uploaded_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Approval. editable=False keeps these out of ordinary forms: they are
    # changed only by save(), approve() and reject() below.
    status = models.CharField(
        max_length=10,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDING,
        editable=False,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="reviewed_documents",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, editable=False)
    rejection_reason = models.TextField(blank=True, editable=False)

    # Ingestion (see processing.py): how many passages the text became,
    # and when that finished. processed_at stays empty until ingestion
    # has fully succeeded; until then the document is never searched
    # and cannot be approved.
    passage_count = models.PositiveIntegerField(default=0, editable=False)
    processed_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = DocumentQuerySet.as_manager()

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # The starting status is decided here, never by the person
        # uploading. Whatever a form or request says, a new document is:
        #   - APPROVED if the uploader may approve documents (Super Admin)
        #   - PENDING for everyone else who may upload (Admin)
        if self._state.adding:
            uploader = self.uploaded_by
            if uploader is None or not user_can(uploader, Action.UPLOAD_DOCUMENT):
                raise PermissionDenied("This user may not upload documents.")
            if user_can(uploader, Action.APPROVE_DOCUMENT):
                self._set_review(DocumentStatus.APPROVED, uploader)
            else:
                self._set_review(DocumentStatus.PENDING, reviewer=None)
        super().save(*args, **kwargs)

    @property
    def is_processed(self):
        return self.processed_at is not None

    def approve(self, reviewer):
        """Make the document part of the active knowledge base."""
        self._require_approver(reviewer)
        if not self.is_processed:
            raise ValidationError(NOT_PROCESSED)
        self._set_review(DocumentStatus.APPROVED, reviewer)
        self.save()

    def reject(self, reviewer, reason):
        """Refuse the document. The reason is shown to the Admin who uploaded it."""
        self._require_approver(reviewer)
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("A reason is required when rejecting a document.")
        self._set_review(DocumentStatus.REJECTED, reviewer, reason)
        self.save()

    def is_visible_to(self, user):
        return Document.objects.visible_to(user).filter(pk=self.pk).exists()

    def _require_approver(self, reviewer):
        if not user_can(reviewer, Action.APPROVE_DOCUMENT):
            raise PermissionDenied("Only a Super Admin can approve or reject documents.")

    def _set_review(self, status, reviewer, reason=""):
        self.status = status
        self.reviewed_by = reviewer
        self.reviewed_at = timezone.now() if reviewer else None
        self.rejection_reason = reason


class Passage(models.Model):
    """A short piece of a document's text (about 120 words), from one section.

    A whole document is too long to give to the language model, so its
    text is cut into passages. A question is answered from the few
    passages that match it best.
    """

    # CASCADE: when a document is deleted, its passages go with it.
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="passages")
    number = models.PositiveIntegerField()  # 1, 2, 3 ... in reading order
    page = models.PositiveIntegerField(null=True, blank=True)  # PDF page; empty for other files
    # The heading this passage sits under, for example "2. Debarment from
    # examinations". Shown with the source. Empty before the first heading.
    section = models.CharField(max_length=200, blank=True)
    text = models.TextField()
    # The passage's keywords, separated and surrounded by spaces, for
    # example " attendance policy student ". Stored once when the document
    # is processed, so a search does not have to work them out every time.
    terms = models.TextField(editable=False)

    class Meta:
        ordering = ["document_id", "number"]

    def __str__(self):
        return f"{self.document.title} #{self.number}"
