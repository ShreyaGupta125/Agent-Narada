"""Every role against every page and every API, in one table.

The table below IS the permission matrix of the README. If a role could
open something it should not (or the other way round), this test fails
and names the role and the address.
"""

from django.test import TestCase

from accounts.models import Role, User

SUPER, ADMIN, STUDENT, TEACHER, STAFF = (
    Role.SUPER_ADMIN, Role.ADMIN, Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF,
)
ROLES = [SUPER, ADMIN, STUDENT, TEACHER, STAFF]
CHATBOT = {STUDENT, TEACHER, STAFF}

# Pages: (address, roles that may open it). Everyone else is sent to their
# own start page; a visitor who is not logged in is sent to /login/.
PAGES = [
    ("/", CHATBOT),
    ("/dashboard/super-admin/", {SUPER}),
    ("/dashboard/admin/", {ADMIN}),
    ("/users/", {SUPER}),
    ("/documents/", {SUPER, ADMIN}),
    ("/documents/upload/", {SUPER, ADMIN}),
]

# APIs: (method, address, roles that may use it). Everyone else gets 403.
APIS = [
    ("get", "/api/users/", {SUPER}),
    ("get", "/api/documents/", {SUPER, ADMIN}),
    ("get", "/api/dashboard/super-admin/", {SUPER}),
    ("get", "/api/dashboard/admin/", {ADMIN}),
    ("post", "/api/chat/", CHATBOT),
    ("get", "/api/chat/conversations/", CHATBOT),
    ("delete", "/api/chat/conversations/", CHATBOT),
]

HOME = {
    SUPER: "/dashboard/super-admin/",
    ADMIN: "/dashboard/admin/",
    STUDENT: "/",
    TEACHER: "/",
    STAFF: "/",
}


class EveryRoleEveryAddressTest(TestCase):
    def test_pages(self):
        for role in ROLES:
            self.client.force_login(User.objects.create_user(username=f"user_{role}", role=role))
            for address, allowed in PAGES:
                with self.subTest(role=role, page=address):
                    response = self.client.get(address)
                    if role in allowed:
                        self.assertEqual(response.status_code, 200)
                    else:
                        self.assertRedirects(response, HOME[role], fetch_redirect_response=False)

    def test_pages_need_login(self):
        for address, _ in PAGES:
            with self.subTest(page=address):
                self.assertRedirects(self.client.get(address), "/login/?next=" + address)

    def test_apis(self):
        for role in ROLES:
            self.client.force_login(User.objects.create_user(username=f"api_{role}", role=role))
            for method, address, allowed in APIS:
                with self.subTest(role=role, api=f"{method.upper()} {address}"):
                    # "Hi" is answered without documents or the model, and
                    # {"confirm": false} deletes nothing: safe to send.
                    body = {"question": "Hi"} if address == "/api/chat/" else {"confirm": False}
                    response = getattr(self.client, method)(address, body, content_type="application/json")
                    if role in allowed:
                        self.assertIn(response.status_code, (200, 400))  # 400: clear-all without confirm
                    else:
                        self.assertEqual(response.status_code, 403)

    def test_apis_need_login(self):
        for method, address, _ in APIS:
            with self.subTest(api=f"{method.upper()} {address}"):
                response = getattr(self.client, method)(address, {}, content_type="application/json")
                self.assertEqual(response.status_code, 403)
