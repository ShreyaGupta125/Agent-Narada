from rest_framework import serializers

from .models import Document

# The largest file that may be uploaded: 10 MB.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

ACCESS_FIELDS = ["for_students", "for_teaching_staff", "for_non_teaching_staff"]

# A file's name can be changed to anything, so the first bytes are checked
# too. Every real file of these types starts with these bytes ("magic
# numbers"). .docx and .odt files are zip files, which start with "PK".
FILE_SIGNATURES = {
    "pdf": (b"%PDF", "a real PDF"),
    "docx": (b"PK\x03\x04", "a real Word (.docx) file"),
    "odt": (b"PK\x03\x04", "a real OpenDocument (.odt) file"),
    "doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "a real Word 97-2003 (.doc) file"),
}


class DocumentUploadSerializer(serializers.ModelSerializer):
    """Checks an upload before anything is stored.

    The status is not in the list of fields on purpose: the person
    uploading cannot send it. The Document model decides it.
    """

    class Meta:
        model = Document
        fields = ["title", "description", "file", *ACCESS_FIELDS]

    def validate_file(self, file):
        # The file type (its extension) is already checked by the model's
        # own validator. Two more checks are made here: the size, and
        # that the file really is what its name says.
        if file.size > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError("The file is larger than 10 MB.")

        extension = file.name.rsplit(".", 1)[-1].lower()
        if extension in FILE_SIGNATURES:
            signature, description = FILE_SIGNATURES[extension]
            beginning = file.read(len(signature))
            file.seek(0)  # go back to the start so the whole file is saved
            if beginning != signature:
                raise serializers.ValidationError(f"This file is not {description}.")
        return file

    def validate(self, data):
        return at_least_one_group(data)


class DocumentAccessSerializer(serializers.ModelSerializer):
    """Changes who may read a document that is already uploaded.

    All three groups must be sent, so a forgotten field can never
    silently keep (or remove) a group.
    """

    class Meta:
        model = Document
        fields = ACCESS_FIELDS
        extra_kwargs = {field: {"required": True} for field in ACCESS_FIELDS}

    def validate(self, data):
        return at_least_one_group(data)


def at_least_one_group(data):
    """A document nobody may read is of no use, so it is refused."""
    if not any(data.get(field) for field in ACCESS_FIELDS):
        raise serializers.ValidationError(
            {"access": "Choose at least one group that may read this document."}
        )
    return data
