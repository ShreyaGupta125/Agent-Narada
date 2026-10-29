from django.contrib import admin, messages

from .models import Document
from .processing import IngestionError, mark_unprocessed, process_document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Lets the Super Admin inspect documents on Django's admin site.

    The status cannot be typed in here: it is shown read-only, because it
    changes only through the approval workflow in the Document model.
    """

    list_display = ("title", "status", "uploaded_by", "uploaded_at", "passage_count", "processed_at")
    list_filter = ("status", "for_students", "for_teaching_staff", "for_non_teaching_staff")
    search_fields = ("title",)
    readonly_fields = (
        "uploaded_by",
        "uploaded_at",
        "status",
        "reviewed_by",
        "reviewed_at",
        "rejection_reason",
        "passage_count",
        "processed_at",
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user  # the uploader is whoever is logged in
        super().save_model(request, obj, form, change)

        # A new or replaced file is read again, exactly as an upload on
        # the Upload Document page is.
        if not change or "file" in form.changed_data:
            try:
                process_document(obj)
            except IngestionError as error:
                mark_unprocessed(obj)
                self.message_user(
                    request,
                    f'The text of "{obj.title}" could not be read, so it is not used for answers: {error}',
                    level=messages.ERROR,
                )
