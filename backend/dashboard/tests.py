import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import Role, User
from documents.models import Document
from documents.processing import process_document

# Test uploads go to a throwaway folder, never to the real media folder.
TEST_MEDIA = tempfile.mkdtemp()

SUPER_ADMIN_STATS = "/api/dashboard/super-admin/"
ADMIN_STATS = "/api/dashboard/admin/"


def make_user(role, username=None, **extra):
    return User.objects.create_user(username=username or role.lower(), role=role, **extra)


def upload(uploader, title="Document"):
    """Store a document and read its text, as the upload page does."""
    document = Document.objects.create(
        title=title, file=SimpleUploadedFile("file.txt", b"Example rules."), uploaded_by=uploader
    )
    return process_document(document)


@override_settings(MEDIA_ROOT=TEST_MEDIA)
class DashboardTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA, ignore_errors=True)


class SuperAdminDashboardTests(DashboardTestCase):
    def setUp(self):
        self.super_admin = make_user(Role.SUPER_ADMIN)
        self.client.force_login(self.super_admin)

    def test_user_totals_by_role(self):
        make_user(Role.ADMIN)
        make_user(Role.STUDENT, username="student1")
        make_user(Role.STUDENT, username="student2")
        make_user(Role.STUDENT, username="student3", is_active=False)
        make_user(Role.TEACHING_STAFF)

        self.assertEqual(
            self.client.get(SUPER_ADMIN_STATS).json()["users"],
            {
                "total": 6,
                "students": 3,  # a deactivated account is still an account
                "teaching_staff": 1,
                "non_teaching_staff": 0,
                "admins": 1,
                "super_admins": 1,
            },
        )

    def test_document_totals_by_status(self):
        admin = make_user(Role.ADMIN)
        upload(admin, "Pending one")
        upload(admin, "Pending two")
        upload(admin, "Rejected").reject(self.super_admin, "Out of date")
        upload(admin, "Approved").approve(self.super_admin)
        upload(self.super_admin, "Approved on upload")

        self.assertEqual(
            self.client.get(SUPER_ADMIN_STATS).json()["documents"],
            {"total": 5, "pending": 2, "approved": 2, "rejected": 1},
        )

    def test_empty_system_shows_zeros(self):
        self.assertEqual(
            self.client.get(SUPER_ADMIN_STATS).json()["documents"],
            {"total": 0, "pending": 0, "approved": 0, "rejected": 0},
        )


class AdminDashboardTests(DashboardTestCase):
    def test_admin_sees_only_their_own_documents(self):
        super_admin = make_user(Role.SUPER_ADMIN)
        meera = make_user(Role.ADMIN, username="meera")
        other_admin = make_user(Role.ADMIN, username="other")

        upload(meera, "Pending")
        upload(meera, "Approved").approve(super_admin)
        upload(meera, "Rejected").reject(super_admin, "Out of date")
        upload(other_admin, "Someone else's")
        upload(super_admin, "Super Admin's")

        self.client.force_login(meera)
        self.assertEqual(
            self.client.get(ADMIN_STATS).json(),
            {"documents": {"total": 3, "pending": 1, "approved": 1, "rejected": 1}},
        )


class DashboardAccessTests(DashboardTestCase):
    """Each dashboard's numbers are for one role only."""

    def test_only_the_right_role_gets_each_dashboards_numbers(self):
        allowed = {SUPER_ADMIN_STATS: Role.SUPER_ADMIN, ADMIN_STATS: Role.ADMIN}
        for role in Role.values:
            self.client.force_login(make_user(role))
            for url, allowed_role in allowed.items():
                with self.subTest(role=role, url=url):
                    expected = 200 if role == allowed_role else 403
                    self.assertEqual(self.client.get(url).status_code, expected)

    def test_anonymous_visitor_is_refused(self):
        for url in (SUPER_ADMIN_STATS, ADMIN_STATS):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_refusal_contains_no_numbers(self):
        self.client.force_login(make_user(Role.STUDENT))
        response = self.client.get(SUPER_ADMIN_STATS)
        self.assertNotIn("users", response.json())
