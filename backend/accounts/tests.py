from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, TestCase

from .models import Role, User
from .permissions import ROLE_HOME, Action, permissions_for, user_can
from .views import LOCKED_OUT, MAX_FAILED_LOGINS


class UserRoleTests(TestCase):
    def test_there_are_exactly_five_roles(self):
        self.assertEqual(
            set(Role.values),
            {"SUPER_ADMIN", "ADMIN", "STUDENT", "TEACHING_STAFF", "NON_TEACHING_STAFF"},
        )

    def test_new_user_is_a_student_by_default(self):
        user = User.objects.create_user(username="asha", password="test-pass-123")
        self.assertEqual(user.role, Role.STUDENT)

    def test_superuser_is_always_super_admin(self):
        user = User.objects.create_superuser(
            username="root", password="test-pass-123", role=Role.STUDENT
        )
        self.assertEqual(user.role, Role.SUPER_ADMIN)

    def test_password_is_stored_hashed_not_as_plain_text(self):
        user = User.objects.create_user(username="asha", password="test-pass-123")
        self.assertNotEqual(user.password, "test-pass-123")
        self.assertTrue(user.check_password("test-pass-123"))


class AuthenticationTests(TestCase):
    PASSWORD = "test-pass-123"

    def setUp(self):
        cache.clear()  # no failed-login counts left over from other tests
        self.user = User.objects.create_user(
            username="asha", password=self.PASSWORD, role=Role.TEACHING_STAFF
        )

    def log_in(self, username="asha", password=PASSWORD):
        return self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password},
            content_type="application/json",
        )

    def test_correct_login_returns_the_user_and_role(self):
        response = self.log_in()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "asha")
        self.assertEqual(response.json()["role"], "TEACHING_STAFF")

    def test_login_reply_never_contains_the_password(self):
        response = self.log_in()
        self.assertNotIn("password", response.json())

    def test_wrong_password_is_refused(self):
        response = self.log_in(password="wrong")
        self.assertEqual(response.status_code, 401)

    def test_unknown_user_gets_the_same_message_as_wrong_password(self):
        wrong_password = self.log_in(password="wrong")
        unknown_user = self.log_in(username="nobody")
        self.assertEqual(unknown_user.status_code, 401)
        self.assertEqual(unknown_user.json(), wrong_password.json())

    def test_deactivated_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.log_in().status_code, 401)

    # ----- protection against guessing passwords -----

    def test_too_many_wrong_passwords_lock_the_username(self):
        for _ in range(MAX_FAILED_LOGINS):
            self.assertEqual(self.log_in(password="guess").status_code, 401)
        # Locked now: even the right password is not checked.
        response = self.log_in()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["detail"], LOCKED_OUT)

    def test_the_lock_is_per_username(self):
        User.objects.create_user(username="ravi", password=self.PASSWORD)
        for _ in range(MAX_FAILED_LOGINS):
            self.log_in(password="guess")
        self.assertEqual(self.log_in(username="ravi").status_code, 200)
        # Upper/lower case does not get around the lock.
        self.assertEqual(self.log_in(username="ASHA").status_code, 429)

    def test_a_successful_login_resets_the_count(self):
        for _ in range(MAX_FAILED_LOGINS - 1):
            self.log_in(password="guess")
        self.assertEqual(self.log_in().status_code, 200)
        self.client.logout()
        for _ in range(MAX_FAILED_LOGINS - 1):
            self.assertEqual(self.log_in(password="guess").status_code, 401)
        self.assertEqual(self.log_in().status_code, 200)

    def test_me_is_refused_without_login(self):
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)

    def test_me_works_after_login(self):
        self.log_in()
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role_label"], "Teaching Staff")

    def test_logout_ends_the_session(self):
        self.log_in()
        self.assertEqual(self.client.post("/api/auth/logout/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 403)

    def test_logout_must_be_a_post(self):
        self.log_in()
        self.assertEqual(self.client.get("/api/auth/logout/").status_code, 405)

    def test_login_without_csrf_token_is_refused(self):
        strict_client = Client(enforce_csrf_checks=True)
        response = strict_client.post(
            "/api/auth/login/",
            {"username": "asha", "password": self.PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_login_with_csrf_token_is_accepted(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.get("/login/")  # the login page sets the csrftoken cookie
        token = strict_client.cookies["csrftoken"].value
        response = strict_client.post(
            "/api/auth/login/",
            {"username": "asha", "password": self.PASSWORD},
            content_type="application/json",
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)


class PageTests(TestCase):
    def test_chat_page_sends_anonymous_visitor_to_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, "/login/?next=/")

    def test_login_page_opens_without_login(self):
        self.assertEqual(self.client.get("/login/").status_code, 200)

    def test_chat_page_opens_after_login(self):
        User.objects.create_user(username="asha", password="test-pass-123")
        self.client.login(username="asha", password="test-pass-123")
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_login_page_sends_logged_in_user_to_chat(self):
        User.objects.create_user(username="asha", password="test-pass-123")
        self.client.login(username="asha", password="test-pass-123")
        self.assertRedirects(self.client.get("/login/"), "/")


def make_user(role, username=None, **extra):
    """A user with the given role. No password: tests log in with force_login."""
    return User.objects.create_user(username=username or role.lower(), role=role, **extra)


class PermissionMatrixTests(TestCase):
    def test_what_each_role_may_do(self):
        chatbot_user = {Action.CHAT, Action.VIEW_OWN_CHAT_HISTORY, Action.DELETE_OWN_CHAT_HISTORY}
        expected = {
            Role.SUPER_ADMIN: {
                Action.SUPER_ADMIN_DASHBOARD,
                Action.MANAGE_USERS,
                Action.UPLOAD_DOCUMENT,
                Action.APPROVE_DOCUMENT,
            },
            Role.ADMIN: {Action.ADMIN_DASHBOARD, Action.UPLOAD_DOCUMENT},
            Role.STUDENT: chatbot_user,
            Role.TEACHING_STAFF: chatbot_user,
            Role.NON_TEACHING_STAFF: chatbot_user,
        }
        for role, actions in expected.items():
            with self.subTest(role=role):
                self.assertEqual(permissions_for(make_user(role)), actions)

    def test_every_role_has_a_row_in_the_matrix(self):
        for role in Role.values:
            with self.subTest(role=role):
                self.assertTrue(permissions_for(make_user(role)))

    def test_only_students_and_staff_get_the_chatbot(self):
        chat_roles = {Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF}
        for role in Role.values:
            with self.subTest(role=role):
                self.assertEqual(user_can(make_user(role), Action.CHAT), role in chat_roles)

    def test_admin_can_upload_but_not_approve(self):
        admin = make_user(Role.ADMIN)
        self.assertTrue(user_can(admin, Action.UPLOAD_DOCUMENT))
        self.assertFalse(user_can(admin, Action.APPROVE_DOCUMENT))

    def test_anonymous_visitor_may_do_nothing(self):
        self.assertEqual(permissions_for(AnonymousUser()), set())

    def test_deactivated_user_may_do_nothing(self):
        user = make_user(Role.SUPER_ADMIN, is_active=False)
        self.assertEqual(permissions_for(user), set())

    def test_unknown_role_may_do_nothing(self):
        user = make_user(Role.STUDENT)
        user.role = "HACKER"
        self.assertEqual(permissions_for(user), set())


class RoleProtectedEndpointTests(TestCase):
    """/api/users/ is for the Super Admin only."""

    def test_only_super_admin_gets_the_user_list(self):
        expected_status = {
            Role.SUPER_ADMIN: 200,
            Role.ADMIN: 403,
            Role.STUDENT: 403,
            Role.TEACHING_STAFF: 403,
            Role.NON_TEACHING_STAFF: 403,
        }
        for role, status in expected_status.items():
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertEqual(self.client.get("/api/users/").status_code, status)

    def test_anonymous_visitor_is_refused(self):
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

    def test_refusal_does_not_leak_any_user_data(self):
        make_user(Role.SUPER_ADMIN, username="secret_admin")
        self.client.force_login(make_user(Role.STUDENT))
        response = self.client.get("/api/users/")
        self.assertNotContains(response, "secret_admin", status_code=403)

    def test_user_list_shows_roles(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        make_user(Role.STUDENT, username="asha")
        rows = {row["username"]: row["role"] for row in self.client.get("/api/users/").json()}
        self.assertEqual(rows, {"asha": "STUDENT", "root": "SUPER_ADMIN"})

    def test_role_change_takes_effect_without_logging_in_again(self):
        user = make_user(Role.STUDENT)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

        user.role = Role.SUPER_ADMIN
        user.save()
        self.assertEqual(self.client.get("/api/users/").status_code, 200)

        user.role = Role.STUDENT
        user.save()
        self.assertEqual(self.client.get("/api/users/").status_code, 403)

    def test_me_lists_the_users_permissions(self):
        self.client.force_login(make_user(Role.ADMIN))
        self.assertEqual(
            self.client.get("/api/auth/me/").json()["permissions"],
            ["admin_dashboard", "upload_document"],
        )


class DjangoAdminSiteTests(TestCase):
    """Django's own admin site follows the role as well."""

    def test_only_super_admin_gets_the_admin_flags(self):
        for role in Role.values:
            with self.subTest(role=role):
                user = make_user(role)
                self.assertEqual(user.is_staff, role == Role.SUPER_ADMIN)
                self.assertEqual(user.is_superuser, role == Role.SUPER_ADMIN)

    def test_demoted_super_admin_loses_the_admin_flags(self):
        user = make_user(Role.SUPER_ADMIN)
        user.role = Role.ADMIN
        user.save()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_flags_cannot_be_set_without_the_role(self):
        user = make_user(Role.STUDENT, is_staff=True, is_superuser=True)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_admin_site_is_closed_to_every_other_role(self):
        for role in Role.values:
            if role == Role.SUPER_ADMIN:
                continue
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                response = self.client.get("/admin/")
                self.assertRedirects(response, "/admin/login/?next=/admin/")

    def test_super_admin_can_open_the_user_pages(self):
        user = make_user(Role.SUPER_ADMIN)
        self.client.force_login(user)
        for url in (
            "/admin/",
            "/admin/accounts/user/",
            "/admin/accounts/user/add/",
            f"/admin/accounts/user/{user.pk}/change/",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class AccountCreationTests(TestCase):
    """Only the Super Admin can create accounts, with any of the five roles."""

    PASSWORD = "Campus-Key-2026"

    def create_account(self, **changes):
        data = {"username": "newuser", "password": self.PASSWORD, "role": "STUDENT"}
        data.update(changes)
        return self.client.post("/api/users/", data, content_type="application/json")

    def test_super_admin_can_create_every_role(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        for role in Role.values:
            with self.subTest(role=role):
                response = self.create_account(username="new_" + role.lower(), role=role)
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["role"], role)
                self.assertEqual(User.objects.get(username="new_" + role.lower()).role, role)

    def test_no_other_role_can_create_accounts(self):
        for role in Role.values:
            if role == Role.SUPER_ADMIN:
                continue
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertEqual(self.create_account(role="SUPER_ADMIN").status_code, 403)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_anonymous_visitor_cannot_create_accounts(self):
        self.assertEqual(self.create_account().status_code, 403)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_created_account_can_log_in_with_its_password(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        self.create_account(first_name="Asha", last_name="Rao", email="asha@example.com")
        self.client.logout()

        response = self.client.post(
            "/api/auth/login/",
            {"username": "newuser", "password": self.PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "Asha Rao")

    def test_password_is_hashed_and_never_sent_back(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        response = self.create_account()
        self.assertNotContains(response, self.PASSWORD, status_code=201)
        self.assertNotEqual(User.objects.get(username="newuser").password, self.PASSWORD)

    def test_created_super_admin_gets_the_admin_flags(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        self.create_account(role="SUPER_ADMIN")
        self.assertTrue(User.objects.get(username="newuser").is_superuser)

    def test_bad_data_is_refused(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        bad_inputs = {
            "username": {"username": "root"},  # already taken
            "role": {"role": "HACKER"},  # not one of the five roles
            "password": {"password": "123"},  # too short, only digits
            "email": {"email": "not-an-email"},
        }
        for field, changes in bad_inputs.items():
            with self.subTest(field=field):
                response = self.create_account(**changes)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_missing_fields_are_refused(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN, username="root"))
        response = self.client.post("/api/users/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.json()), {"username", "password", "role"})


class ManageUsersPageTests(TestCase):
    def test_super_admin_can_open_the_page(self):
        self.client.force_login(make_user(Role.SUPER_ADMIN))
        self.assertEqual(self.client.get("/users/").status_code, 200)

    def test_every_other_role_is_sent_to_its_own_start_page(self):
        for role in Role.values:
            if role == Role.SUPER_ADMIN:
                continue
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertRedirects(self.client.get("/users/"), ROLE_HOME[role])

    def test_anonymous_visitor_is_sent_to_login(self):
        self.assertRedirects(self.client.get("/users/"), "/login/?next=/users/")


class RoleRoutingTests(TestCase):
    """After login each role is taken to its own page, and Django refuses
    the pages that belong to other roles."""

    CHAT = "/"
    SUPER_ADMIN_DASHBOARD = "/dashboard/super-admin/"
    ADMIN_DASHBOARD = "/dashboard/admin/"

    HOME = {
        Role.SUPER_ADMIN: SUPER_ADMIN_DASHBOARD,
        Role.ADMIN: ADMIN_DASHBOARD,
        Role.STUDENT: CHAT,
        Role.TEACHING_STAFF: CHAT,
        Role.NON_TEACHING_STAFF: CHAT,
    }

    def test_login_reply_names_the_roles_start_page(self):
        for role, home in self.HOME.items():
            with self.subTest(role=role):
                make_user(role, password="test-pass-123")
                response = self.client.post(
                    "/api/auth/login/",
                    {"username": role.lower(), "password": "test-pass-123"},
                    content_type="application/json",
                )
                self.assertEqual(response.json()["home"], home)

    def test_each_role_can_open_its_own_start_page(self):
        for role, home in self.HOME.items():
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertEqual(self.client.get(home).status_code, 200)

    def test_every_other_page_sends_the_user_back_to_their_own(self):
        pages = [self.CHAT, self.SUPER_ADMIN_DASHBOARD, self.ADMIN_DASHBOARD, "/users/"]
        allowed = {
            Role.SUPER_ADMIN: {self.SUPER_ADMIN_DASHBOARD, "/users/"},
            Role.ADMIN: {self.ADMIN_DASHBOARD},
            Role.STUDENT: {self.CHAT},
            Role.TEACHING_STAFF: {self.CHAT},
            Role.NON_TEACHING_STAFF: {self.CHAT},
        }
        for role, home in self.HOME.items():
            self.client.force_login(make_user(role))
            for page in pages:
                with self.subTest(role=role, page=page):
                    response = self.client.get(page)
                    if page in allowed[role]:
                        self.assertEqual(response.status_code, 200)
                    else:
                        self.assertRedirects(response, home)

    def test_super_admin_and_admin_never_receive_the_chat_page(self):
        for role in (Role.SUPER_ADMIN, Role.ADMIN):
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                response = self.client.get(self.CHAT)
                self.assertEqual(response.status_code, 302)
                self.assertNotContains(response, "chat-form", status_code=302)

    def test_login_page_sends_a_logged_in_user_to_their_start_page(self):
        for role, home in self.HOME.items():
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertRedirects(self.client.get("/login/"), home)

    def test_anonymous_visitor_is_sent_to_login_from_every_page(self):
        for page in (self.CHAT, self.SUPER_ADMIN_DASHBOARD, self.ADMIN_DASHBOARD):
            with self.subTest(page=page):
                self.assertRedirects(self.client.get(page), "/login/?next=" + page)

    def test_role_with_no_permissions_is_refused_not_redirected_forever(self):
        user = make_user(Role.STUDENT)
        User.objects.filter(pk=user.pk).update(role="HACKER")
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.CHAT).status_code, 403)


class AccountModifyAndDeleteTests(TestCase):
    """Only the Super Admin can modify or delete accounts."""

    def setUp(self):
        self.root = make_user(Role.SUPER_ADMIN, username="root")
        self.target = make_user(Role.STUDENT, username="asha", password="Old-Campus-Key-1")
        self.client.force_login(self.root)

    def modify(self, user, **changes):
        return self.client.patch(
            f"/api/users/{user.pk}/", changes, content_type="application/json"
        )

    def delete(self, user):
        return self.client.delete(f"/api/users/{user.pk}/")

    # ----- modify -----

    def test_super_admin_can_modify_an_account(self):
        response = self.modify(
            self.target,
            username="asha_rao",
            first_name="Asha",
            last_name="Rao",
            email="asha@example.com",
            role="TEACHING_STAFF",
        )
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, "asha_rao")
        self.assertEqual(self.target.get_full_name(), "Asha Rao")
        self.assertEqual(self.target.email, "asha@example.com")
        self.assertEqual(self.target.role, Role.TEACHING_STAFF)

    def test_only_the_fields_that_are_sent_are_changed(self):
        self.modify(self.target, first_name="Asha")
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Asha")
        self.assertEqual(self.target.role, Role.STUDENT)
        self.assertTrue(self.target.is_active)

    def test_deactivated_account_cannot_log_in_and_can_be_reactivated(self):
        credentials = {"username": "asha", "password": "Old-Campus-Key-1"}
        other_browser = Client()

        self.modify(self.target, is_active=False)
        response = other_browser.post("/api/auth/login/", credentials, content_type="application/json")
        self.assertEqual(response.status_code, 401)

        self.modify(self.target, is_active=True)
        response = other_browser.post("/api/auth/login/", credentials, content_type="application/json")
        self.assertEqual(response.status_code, 200)

    def test_new_password_replaces_the_old_one(self):
        self.modify(self.target, password="New-Campus-Key-2")
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("New-Campus-Key-2"))
        self.assertFalse(self.target.check_password("Old-Campus-Key-1"))

    def test_empty_password_keeps_the_current_one(self):
        self.modify(self.target, first_name="Asha", password="")
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("Old-Campus-Key-1"))

    def test_promoted_account_gets_the_admin_flags_and_demoted_loses_them(self):
        self.modify(self.target, role="SUPER_ADMIN")
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_superuser)

        self.modify(self.target, role="ADMIN")
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_superuser)

    def test_bad_changes_are_refused(self):
        bad_changes = {
            "username": {"username": "root"},  # already taken
            "role": {"role": "HACKER"},
            "password": {"password": "123"},
            "email": {"email": "not-an-email"},
        }
        for field, changes in bad_changes.items():
            with self.subTest(field=field):
                response = self.modify(self.target, **changes)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json())
        self.target.refresh_from_db()
        self.assertEqual(self.target.username, "asha")
        self.assertEqual(self.target.role, Role.STUDENT)

    def test_reply_never_contains_the_password(self):
        response = self.modify(self.target, password="New-Campus-Key-2")
        self.assertNotIn("password", response.json())
        self.assertNotContains(response, "New-Campus-Key-2")

    # ----- delete -----

    def test_super_admin_can_delete_an_account(self):
        self.assertEqual(self.delete(self.target).status_code, 204)
        self.assertFalse(User.objects.filter(username="asha").exists())

    def test_deleting_an_account_that_does_not_exist_gives_404(self):
        self.target.delete()
        self.assertEqual(self.client.delete("/api/users/999999/").status_code, 404)

    # ----- a Super Admin cannot lock themselves out -----

    def test_super_admin_cannot_delete_their_own_account(self):
        self.assertEqual(self.delete(self.root).status_code, 400)
        self.assertTrue(User.objects.filter(username="root").exists())

    def test_super_admin_cannot_change_their_own_role(self):
        response = self.modify(self.root, role="STUDENT")
        self.assertEqual(response.status_code, 400)
        self.root.refresh_from_db()
        self.assertEqual(self.root.role, Role.SUPER_ADMIN)

    def test_super_admin_cannot_deactivate_their_own_account(self):
        response = self.modify(self.root, is_active=False)
        self.assertEqual(response.status_code, 400)
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_active)

    def test_super_admin_can_change_their_own_details_and_stay_logged_in(self):
        response = self.modify(self.root, first_name="Root", password="Root-Campus-Key-3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/users/").status_code, 200)

    # ----- every other role is refused -----

    def test_no_other_role_can_modify_or_delete(self):
        for role in Role.values:
            if role == Role.SUPER_ADMIN:
                continue
            with self.subTest(role=role):
                self.client.force_login(make_user(role))
                self.assertEqual(self.modify(self.target, role="SUPER_ADMIN").status_code, 403)
                self.assertEqual(self.delete(self.target).status_code, 403)
                # Not even their own account.
                own_account = User.objects.get(username=role.lower())
                self.assertEqual(self.modify(own_account, role="SUPER_ADMIN").status_code, 403)
        self.target.refresh_from_db()
        self.assertEqual(self.target.role, Role.STUDENT)

    def test_anonymous_visitor_cannot_modify_or_delete(self):
        self.client.logout()
        self.assertEqual(self.modify(self.target, role="SUPER_ADMIN").status_code, 403)
        self.assertEqual(self.delete(self.target).status_code, 403)
        self.assertTrue(User.objects.filter(username="asha").exists())

    def test_list_marks_the_super_admins_own_row(self):
        rows = {row["username"]: row for row in self.client.get("/api/users/").json()}
        self.assertTrue(rows["root"]["is_self"])
        self.assertFalse(rows["asha"]["is_self"])
        self.assertEqual(rows["asha"]["id"], self.target.pk)
