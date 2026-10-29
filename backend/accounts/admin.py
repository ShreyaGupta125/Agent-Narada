from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class NaradaUserAdmin(UserAdmin):
    """Shows users on Django's admin site, with the role field added
    to the pages UserAdmin already provides."""

    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")

    # Edit page for an existing user. Django's own is_staff / is_superuser
    # switches are left out on purpose: they are set from the role.
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Agent Narada", {"fields": ("role", "is_active")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    # "Add user" page.
    add_fieldsets = UserAdmin.add_fieldsets + (("Agent Narada", {"fields": ("role",)}),)
