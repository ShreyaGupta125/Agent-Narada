import re

from django.test import TestCase

from accounts.models import Role, User


class AssetVersionTests(TestCase):
    """Every page asks for its CSS and JavaScript with a version number,
    so browsers never keep using an old copy after an update."""

    def test_every_page_versions_its_css_and_javascript(self):
        pages = {
            "/login/": None,
            "/": Role.STUDENT,
            "/dashboard/super-admin/": Role.SUPER_ADMIN,
            "/users/": Role.SUPER_ADMIN,
            "/documents/": Role.SUPER_ADMIN,
            "/documents/upload/": Role.SUPER_ADMIN,
            "/dashboard/admin/": Role.ADMIN,
        }
        for page, role in pages.items():
            with self.subTest(page=page):
                self.client.logout()
                if role:
                    user, _ = User.objects.get_or_create(username=role.lower(), role=role)
                    self.client.force_login(user)
                html = self.client.get(page).content.decode()

                files = re.findall(r'/static/[\w.]+\.(?:js|css)[^"]*', html)
                self.assertTrue(files)
                for address in files:
                    self.assertRegex(address, r"\?v=\d+$")
