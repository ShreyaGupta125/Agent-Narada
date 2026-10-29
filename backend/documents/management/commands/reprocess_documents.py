"""python manage.py reprocess_documents

Reads the text of every stored document again and rebuilds its passages.
Run it after the way documents are read or split has been improved, so
documents uploaded earlier get the same treatment as new ones.

A document whose text can no longer be read is taken out of search
(marked not processed) and listed, so the Super Admin can deal with it.
"""

from django.core.management.base import BaseCommand

from documents.models import Document
from documents.processing import IngestionError, mark_unprocessed, process_document


class Command(BaseCommand):
    help = "Read every stored document again and rebuild its searchable passages."

    def handle(self, *args, **options):
        done, failed = 0, 0
        for document in Document.objects.order_by("pk"):
            try:
                process_document(document)
                done += 1
            except IngestionError as error:
                mark_unprocessed(document)
                failed += 1
                self.stderr.write(f'NOT READ: "{document.title}" (id {document.pk}): {error}')
        self.stdout.write(f"Processed {done} document(s). {failed} could not be read.")
