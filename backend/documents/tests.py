import shutil
import tempfile
from unittest import mock

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Role, User

from .models import NOT_PROCESSED, Document, DocumentStatus
from .processing import process_document

# Test uploads go to a throwaway folder, never to the real media folder.
TEST_MEDIA = tempfile.mkdtemp()


def make_user(role, username=None, **extra):
    return User.objects.create_user(username=username or role.lower(), role=role, **extra)


def make_pdf(pages):
    """Build a small but real PDF file, one string of text per page."""
    count = len(pages)
    kids = " ".join(f"{4 + 2 * index} 0 R" for index in range(count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * index} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))

    data = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(data))
        data += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_position = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    data += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_position,
    )
    return data


def upload(uploader, title="Attendance Policy", filename="policy.txt", processed=True, **access):
    """Store a document as an upload does. processed=False leaves its
    text unread, as if ingestion had never happened."""
    document = Document.objects.create(
        title=title,
        file=SimpleUploadedFile(filename, b"example content"),
        uploaded_by=uploader,
        **access,
    )
    return process_document(document) if processed else document


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class DocumentTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)

    def setUp(self):
        self.super_admin = make_user(Role.SUPER_ADMIN)
        self.admin = make_user(Role.ADMIN)
        self.student = make_user(Role.STUDENT)


class UploadTests(DocumentTestCase):
    def test_admin_upload_starts_as_pending(self):
        document = upload(self.admin)
        self.assertEqual(document.status, DocumentStatus.PENDING)
        self.assertIsNone(document.reviewed_by)
        self.assertIsNone(document.reviewed_at)

    def test_admin_cannot_make_their_own_upload_active(self):
        # Even if the request asks for APPROVED, the model decides.
        document = Document.objects.create(
            title="Sneaky",
            file=SimpleUploadedFile("sneaky.pdf", b"x"),
            uploaded_by=self.admin,
            status=DocumentStatus.APPROVED,
        )
        self.assertEqual(document.status, DocumentStatus.PENDING)

    def test_super_admin_upload_is_approved_immediately(self):
        document = upload(self.super_admin)
        self.assertEqual(document.status, DocumentStatus.APPROVED)
        self.assertEqual(document.reviewed_by, self.super_admin)
        self.assertIsNotNone(document.reviewed_at)

    def test_chatbot_roles_cannot_upload(self):
        for role in (Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF):
            with self.subTest(role=role):
                user = User.objects.filter(role=role).first() or make_user(role)
                with self.assertRaises(PermissionDenied):
                    upload(user)
        self.assertEqual(Document.objects.count(), 0)

    def test_document_needs_an_uploader(self):
        with self.assertRaises(PermissionDenied):
            upload(None)

    def test_only_document_file_types_are_valid(self):
        cases = [
            ("a.pdf", True), ("a.txt", True), ("a.docx", True), ("a.DOC", True), ("a.odt", True),
            ("a.exe", False), ("a.html", False), ("a.xlsx", False), ("a.zip", False),
        ]
        for filename, valid in cases:
            with self.subTest(filename=filename):
                document = Document(
                    title="File type",
                    file=SimpleUploadedFile(filename, b"x"),
                    uploaded_by=self.admin,
                )
                if valid:
                    document.full_clean()
                else:
                    with self.assertRaises(ValidationError):
                        document.full_clean()


class ApprovalTests(DocumentTestCase):
    def test_super_admin_can_approve(self):
        document = upload(self.admin)
        document.approve(self.super_admin)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.APPROVED)
        self.assertEqual(document.reviewed_by, self.super_admin)
        self.assertIsNotNone(document.reviewed_at)

    def test_super_admin_can_reject_with_a_reason(self):
        document = upload(self.admin)
        document.reject(self.super_admin, "Out of date")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.REJECTED)
        self.assertEqual(document.rejection_reason, "Out of date")

    def test_rejecting_needs_a_reason(self):
        document = upload(self.admin)
        for reason in ("", "   ", None):
            with self.subTest(reason=reason):
                with self.assertRaises(ValidationError):
                    document.reject(self.super_admin, reason)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.PENDING)

    def test_approving_a_rejected_document_clears_the_reason(self):
        document = upload(self.admin)
        document.reject(self.super_admin, "Out of date")
        document.approve(self.super_admin)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.APPROVED)
        self.assertEqual(document.rejection_reason, "")

    def test_nobody_else_can_approve_or_reject(self):
        document = upload(self.admin)
        for user in (self.admin, self.student):
            with self.subTest(role=user.role):
                with self.assertRaises(PermissionDenied):
                    document.approve(user)
                with self.assertRaises(PermissionDenied):
                    document.reject(user, "No")
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.PENDING)

    def test_a_document_whose_text_was_not_read_cannot_be_approved(self):
        document = upload(self.admin, processed=False)
        with self.assertRaisesMessage(ValidationError, NOT_PROCESSED):
            document.approve(self.super_admin)
        document.refresh_from_db()
        self.assertEqual(document.status, DocumentStatus.PENDING)

    def test_document_survives_when_its_uploader_is_deleted(self):
        document = upload(self.admin)
        self.admin.delete()
        document.refresh_from_db()
        self.assertIsNone(document.uploaded_by)


class RoleAccessTests(DocumentTestCase):
    """Which documents each role may get answers from."""

    def setUp(self):
        super().setUp()
        self.teacher = make_user(Role.TEACHING_STAFF)
        self.staff = make_user(Role.NON_TEACHING_STAFF)

    def titles_for(self, user):
        return set(Document.objects.visible_to(user).values_list("title", flat=True))

    def test_each_role_sees_only_documents_opened_to_it(self):
        upload(self.super_admin, title="For students", for_students=True)
        upload(self.super_admin, title="For teachers", for_teaching_staff=True)
        upload(self.super_admin, title="For staff", for_non_teaching_staff=True)
        upload(
            self.super_admin,
            title="For everyone",
            for_students=True,
            for_teaching_staff=True,
            for_non_teaching_staff=True,
        )
        upload(self.super_admin, title="For nobody")

        self.assertEqual(self.titles_for(self.student), {"For students", "For everyone"})
        self.assertEqual(self.titles_for(self.teacher), {"For teachers", "For everyone"})
        self.assertEqual(self.titles_for(self.staff), {"For staff", "For everyone"})

    def test_pending_and_rejected_documents_are_never_visible(self):
        pending = upload(self.admin, title="Pending", for_students=True)
        rejected = upload(self.admin, title="Rejected", for_students=True)
        rejected.reject(self.super_admin, "Out of date")
        self.assertEqual(self.titles_for(self.student), set())
        self.assertFalse(pending.is_visible_to(self.student))

        pending.approve(self.super_admin)
        self.assertEqual(self.titles_for(self.student), {"Pending"})
        self.assertTrue(pending.is_visible_to(self.student))

    def test_super_admin_and_admin_have_no_chatbot_documents(self):
        upload(self.super_admin, for_students=True, for_teaching_staff=True)
        self.assertEqual(self.titles_for(self.super_admin), set())
        self.assertEqual(self.titles_for(self.admin), set())

    def test_deactivated_user_sees_nothing(self):
        upload(self.super_admin, for_students=True)
        self.student.is_active = False
        self.student.save()
        self.assertEqual(self.titles_for(self.student), set())

    def test_a_document_whose_text_was_not_read_is_never_visible(self):
        # A Super Admin's upload is approved at once; without processing
        # it must still stay out of every search.
        upload(self.super_admin, title="Unread", for_students=True, processed=False)
        self.assertEqual(self.titles_for(self.student), set())


class DjangoAdminPagesTests(DocumentTestCase):
    """The Super Admin can inspect the new tables on Django's admin site."""

    def test_super_admin_can_open_the_new_admin_pages(self):
        document = upload(self.super_admin)
        self.client.force_login(self.super_admin)
        for url in (
            "/admin/documents/document/",
            "/admin/documents/document/add/",
            f"/admin/documents/document/{document.pk}/change/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_private_chat_history_is_not_on_the_admin_site(self):
        self.client.force_login(self.super_admin)
        for url in ("/admin/chat/conversation/", "/admin/chat/message/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)


PDF = make_pdf(["Students must attend 75% of classes."])


class DocumentApiTestCase(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.other_admin = make_user(Role.ADMIN, username="other_admin")

    def post_upload(self, filename="policy.pdf", content=PDF, **changes):
        data = {
            "title": "Attendance Policy",
            "description": "Rules for attendance",
            "file": SimpleUploadedFile(filename, content),
            "for_students": "true",
        }
        data.update(changes)
        return self.client.post("/api/documents/", data)  # sent as a multipart form

    def titles(self, query=""):
        return {row["title"] for row in self.client.get("/api/documents/" + query).json()}


class UploadApiTests(DocumentApiTestCase):
    def test_admin_upload_is_stored_as_pending(self):
        self.client.force_login(self.admin)
        response = self.post_upload()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "PENDING")
        self.assertEqual(response.json()["access"], ["Students"])

        document = Document.objects.get()
        self.assertEqual(document.uploaded_by, self.admin)
        self.assertTrue(document.file.storage.exists(document.file.name))

    def test_admin_cannot_send_a_status_or_another_uploader(self):
        self.client.force_login(self.admin)
        response = self.post_upload(status="APPROVED", uploaded_by=self.super_admin.pk)
        self.assertEqual(response.status_code, 201)
        document = Document.objects.get()
        self.assertEqual(document.status, DocumentStatus.PENDING)
        self.assertEqual(document.uploaded_by, self.admin)

    def test_super_admin_upload_is_approved_immediately(self):
        self.client.force_login(self.super_admin)
        self.assertEqual(self.post_upload().json()["status"], "APPROVED")

    def test_chatbot_roles_and_anonymous_visitors_cannot_upload(self):
        self.assertEqual(self.post_upload().status_code, 403)
        for role in (Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF):
            with self.subTest(role=role):
                self.client.force_login(User.objects.filter(role=role).first() or make_user(role))
                self.assertEqual(self.post_upload().status_code, 403)
        self.assertEqual(Document.objects.count(), 0)

    def test_bad_uploads_are_refused(self):
        self.client.force_login(self.admin)
        bad_uploads = {
            "wrong file type": ({"filename": "virus.exe"}, "file"),
            "fake pdf": ({"filename": "fake.pdf", "content": b"MZ not a pdf"}, "file"),
            "no title": ({"title": ""}, "title"),
            "no audience": ({"for_students": "false"}, "access"),
        }
        for name, (changes, field) in bad_uploads.items():
            with self.subTest(name):
                response = self.post_upload(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertEqual(Document.objects.count(), 0)

    def test_file_that_is_too_large_is_refused(self):
        self.client.force_login(self.admin)
        with mock.patch("documents.serializers.MAX_UPLOAD_BYTES", 10):
            response = self.post_upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("file", response.json())

    def test_text_files_are_accepted(self):
        self.client.force_login(self.admin)
        response = self.post_upload(filename="notes.txt", content=b"plain text")
        self.assertEqual(response.status_code, 201)


class DocumentListApiTests(DocumentApiTestCase):
    def setUp(self):
        super().setUp()
        upload(self.admin, title="Mine pending", for_students=True)
        upload(self.admin, title="Mine approved", for_students=True).approve(self.super_admin)
        upload(self.other_admin, title="Other admin", for_students=True)
        upload(self.super_admin, title="Super admin", for_students=True)

    def test_admin_sees_only_their_own_documents(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.titles(), {"Mine pending", "Mine approved"})

    def test_super_admin_sees_every_document(self):
        self.client.force_login(self.super_admin)
        self.assertEqual(
            self.titles(), {"Mine pending", "Mine approved", "Other admin", "Super admin"}
        )

    def test_list_can_be_filtered_by_status(self):
        self.client.force_login(self.super_admin)
        self.assertEqual(self.titles("?status=PENDING"), {"Mine pending", "Other admin"})
        self.assertEqual(self.titles("?status=APPROVED"), {"Mine approved", "Super admin"})
        self.assertEqual(self.titles("?status=REJECTED"), set())

    def test_chatbot_roles_and_anonymous_visitors_get_no_list(self):
        self.assertEqual(self.client.get("/api/documents/").status_code, 403)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get("/api/documents/").status_code, 403)


class ApprovalApiTests(DocumentApiTestCase):
    def setUp(self):
        super().setUp()
        self.document = upload(self.admin, for_students=True)
        self.url = f"/api/documents/{self.document.pk}/"

    def reject(self, reason):
        return self.client.post(
            self.url + "reject/", {"reason": reason}, content_type="application/json"
        )

    def test_super_admin_can_approve(self):
        self.client.force_login(self.super_admin)
        response = self.client.post(self.url + "approve/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "APPROVED")
        self.assertEqual(response.json()["reviewed_by"], self.super_admin.username)
        self.assertTrue(self.document.is_visible_to(self.student))

    def test_super_admin_can_reject_with_a_reason(self):
        self.client.force_login(self.super_admin)
        response = self.reject("Out of date")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "REJECTED")
        self.assertEqual(response.json()["rejection_reason"], "Out of date")
        self.assertFalse(self.document.is_visible_to(self.student))

    def test_rejecting_without_a_reason_is_refused(self):
        self.client.force_login(self.super_admin)
        self.assertEqual(self.reject("  ").status_code, 400)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.PENDING)

    def test_admin_cannot_approve_or_reject_even_their_own_document(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(self.url + "approve/").status_code, 403)
        self.assertEqual(self.reject("No").status_code, 403)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, DocumentStatus.PENDING)

    def test_the_admin_sees_the_rejection_reason(self):
        self.client.force_login(self.super_admin)
        self.reject("Out of date")
        self.client.force_login(self.admin)
        row = self.client.get("/api/documents/").json()[0]
        self.assertEqual(row["status"], "REJECTED")
        self.assertEqual(row["rejection_reason"], "Out of date")

    def test_unknown_document_gives_404(self):
        self.client.force_login(self.super_admin)
        self.assertEqual(self.client.post("/api/documents/999999/approve/").status_code, 404)

    def test_approving_a_document_whose_text_was_not_read_is_refused(self):
        unread = upload(self.admin, title="Unread", processed=False)
        self.client.force_login(self.super_admin)
        response = self.client.post(f"/api/documents/{unread.pk}/approve/")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], NOT_PROCESSED)
        unread.refresh_from_db()
        self.assertEqual(unread.status, DocumentStatus.PENDING)


class FileDownloadApiTests(DocumentApiTestCase):
    def setUp(self):
        super().setUp()
        self.document = upload(self.admin, for_students=True)
        self.url = f"/api/documents/{self.document.pk}/file/"

    def test_uploader_and_super_admin_can_download(self):
        for user in (self.admin, self.super_admin):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"example content")
                self.assertIn("attachment", response["Content-Disposition"])

    def test_another_admin_cannot_download(self):
        self.client.force_login(self.other_admin)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_chatbot_roles_and_anonymous_visitors_cannot_download(self):
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_uploaded_files_have_no_direct_web_address(self):
        self.client.force_login(self.super_admin)
        for prefix in ("/media/", "/static/", "/"):
            with self.subTest(prefix=prefix):
                response = self.client.get(prefix + self.document.file.name)
                self.assertEqual(response.status_code, 404)


class DeleteApiTests(DocumentApiTestCase):
    def delete(self, document):
        return self.client.delete(f"/api/documents/{document.pk}/")

    def test_admin_can_delete_their_own_pending_or_rejected_document(self):
        pending = upload(self.admin, title="Pending")
        rejected = upload(self.admin, title="Rejected")
        rejected.reject(self.super_admin, "Out of date")
        stored_name = pending.file.name

        self.client.force_login(self.admin)
        self.assertEqual(self.delete(pending).status_code, 204)
        self.assertEqual(self.delete(rejected).status_code, 204)
        self.assertEqual(Document.objects.count(), 0)
        # The file is removed from the media folder as well.
        self.assertFalse(pending.file.storage.exists(stored_name))

    def test_admin_cannot_delete_their_own_approved_document(self):
        document = upload(self.admin)
        document.approve(self.super_admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.delete(document).status_code, 400)
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())

    def test_admin_cannot_delete_another_admins_document(self):
        document = upload(self.other_admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.delete(document).status_code, 404)
        self.assertTrue(Document.objects.filter(pk=document.pk).exists())

    def test_super_admin_can_delete_any_document(self):
        document = upload(self.admin)
        document.approve(self.super_admin)
        self.client.force_login(self.super_admin)
        self.assertEqual(self.delete(document).status_code, 204)
        self.assertEqual(Document.objects.count(), 0)

    def test_list_says_which_documents_the_viewer_may_delete(self):
        upload(self.admin, title="Pending")
        upload(self.admin, title="Approved").approve(self.super_admin)
        self.client.force_login(self.admin)
        rows = {row["title"]: row["can_delete"] for row in self.client.get("/api/documents/").json()}
        self.assertEqual(rows, {"Pending": True, "Approved": False})

    def test_chatbot_roles_cannot_delete(self):
        document = upload(self.admin)
        self.client.force_login(self.student)
        self.assertEqual(self.delete(document).status_code, 403)


class ChangeAccessApiTests(DocumentApiTestCase):
    """Correcting "Who may read" after the upload, without uploading again."""

    EVERYONE_BUT_NON_TEACHING = {
        "for_students": True,
        "for_teaching_staff": True,
        "for_non_teaching_staff": False,
    }

    def change(self, document, data=None):
        return self.client.patch(
            f"/api/documents/{document.pk}/",
            data if data is not None else self.EVERYONE_BUT_NON_TEACHING,
            content_type="application/json",
        )

    def test_super_admin_can_change_an_approved_document_and_it_stays_approved(self):
        document = upload(self.super_admin, for_students=True)  # approved at once
        passages = document.passage_count
        self.client.force_login(self.super_admin)

        response = self.change(document)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["access"], ["Students", "Teaching staff"])

        document.refresh_from_db()
        self.assertTrue(document.for_teaching_staff)
        self.assertEqual(document.status, DocumentStatus.APPROVED)
        self.assertEqual(document.passage_count, passages)  # the text is not read again

    def test_the_new_readers_are_used_by_the_chatbot_at_once(self):
        from documents.retrieval import search

        document = Document.objects.create(
            title="Attendance Notice",
            file=SimpleUploadedFile("notice.txt", b"Every student must attend at least 75% of the classes."),
            uploaded_by=self.super_admin,
            for_students=True,
        )
        process_document(document)
        teacher = make_user(Role.TEACHING_STAFF)
        self.assertEqual(search(teacher, "minimum attendance"), [])

        self.client.force_login(self.super_admin)
        self.assertEqual(self.change(document).status_code, 200)
        self.assertEqual([p.document_id for p in search(teacher, "minimum attendance")], [document.pk])

        # And taken away again.
        self.change(document, {"for_students": True, "for_teaching_staff": False, "for_non_teaching_staff": False})
        self.assertEqual(search(teacher, "minimum attendance"), [])

    def test_at_least_one_group_is_required(self):
        document = upload(self.super_admin, for_students=True)
        self.client.force_login(self.super_admin)
        nobody = {"for_students": False, "for_teaching_staff": False, "for_non_teaching_staff": False}
        response = self.change(document, nobody)
        self.assertEqual(response.status_code, 400)
        self.assertIn("access", response.json())
        document.refresh_from_db()
        self.assertTrue(document.for_students)

    def test_all_three_groups_must_be_sent(self):
        document = upload(self.super_admin, for_students=True)
        self.client.force_login(self.super_admin)
        response = self.change(document, {"for_teaching_staff": True})
        self.assertEqual(response.status_code, 400)
        document.refresh_from_db()
        self.assertFalse(document.for_teaching_staff)

    def test_only_the_access_fields_can_be_changed(self):
        document = upload(self.admin, title="Original", for_students=True)
        self.client.force_login(self.admin)
        data = {**self.EVERYONE_BUT_NON_TEACHING, "title": "Changed", "status": "APPROVED"}
        self.assertEqual(self.change(document, data).status_code, 200)
        document.refresh_from_db()
        self.assertEqual(document.title, "Original")
        self.assertEqual(document.status, DocumentStatus.PENDING)

    def test_admin_can_change_their_own_pending_or_rejected_document(self):
        pending = upload(self.admin, title="Pending", for_students=True)
        rejected = upload(self.admin, title="Rejected", for_students=True)
        rejected.reject(self.super_admin, "Wrong readers")
        self.client.force_login(self.admin)
        self.assertEqual(self.change(pending).status_code, 200)
        self.assertEqual(self.change(rejected).status_code, 200)

    def test_admin_cannot_change_their_own_approved_document(self):
        document = upload(self.admin, for_students=True)
        document.approve(self.super_admin)
        self.client.force_login(self.admin)
        self.assertEqual(self.change(document).status_code, 400)
        document.refresh_from_db()
        self.assertFalse(document.for_teaching_staff)

    def test_admin_cannot_change_another_admins_document(self):
        document = upload(self.other_admin, for_students=True)
        self.client.force_login(self.admin)
        self.assertEqual(self.change(document).status_code, 404)

    def test_chatbot_roles_cannot_change_readers(self):
        document = upload(self.admin, for_students=True)
        self.client.force_login(self.student)
        self.assertEqual(self.change(document).status_code, 403)
        document.refresh_from_db()
        self.assertFalse(document.for_teaching_staff)

    def test_list_says_which_documents_the_viewer_may_change(self):
        upload(self.admin, title="Pending", for_students=True)
        upload(self.admin, title="Approved", for_students=True).approve(self.super_admin)
        self.client.force_login(self.admin)
        rows = {row["title"]: row["can_change_access"] for row in self.client.get("/api/documents/").json()}
        self.assertEqual(rows, {"Pending": True, "Approved": False})


class DocumentPagesTests(DocumentTestCase):
    PAGES = ("/documents/", "/documents/upload/")

    def test_admin_and_super_admin_can_open_the_document_pages(self):
        for user in (self.admin, self.super_admin):
            self.client.force_login(user)
            for page in self.PAGES:
                with self.subTest(role=user.role, page=page):
                    self.assertEqual(self.client.get(page).status_code, 200)

    def test_chatbot_roles_are_sent_back_to_the_chat(self):
        self.client.force_login(self.student)
        for page in self.PAGES:
            with self.subTest(page=page):
                self.assertRedirects(self.client.get(page), "/")

    def test_anonymous_visitor_is_sent_to_login(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                self.assertRedirects(self.client.get(page), "/login/?next=" + page)
