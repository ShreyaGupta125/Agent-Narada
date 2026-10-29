from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class Role(models.TextChoices):
    """The five roles a user of Agent Narada can have.

    Left side  = the value stored in the database.
    Right side = the label a human sees.
    """

    SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
    ADMIN = "ADMIN", "Admin"
    STUDENT = "STUDENT", "Student"
    TEACHING_STAFF = "TEACHING_STAFF", "Teaching Staff"
    NON_TEACHING_STAFF = "NON_TEACHING_STAFF", "Non-Teaching Staff"


class NaradaUserManager(UserManager):
    """Creates users. Only one rule is added to Django's own manager:
    an account made with `createsuperuser` is always a SUPER_ADMIN."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields["role"] = Role.SUPER_ADMIN
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Agent Narada's user.

    AbstractUser already provides username, password (stored hashed),
    email, first/last name and the login machinery. We add one field: role.
    """

    # Every new account starts as the least privileged role. A higher role
    # is only ever given by the backend, never chosen by the user at signup.
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STUDENT,
    )

    objects = NaradaUserManager()

    def save(self, *args, **kwargs):
        # Django's admin site is opened by two built-in flags, is_staff and
        # is_superuser. They always follow the role, so the role is the one
        # source of truth and the two can never disagree.
        is_super_admin = self.role == Role.SUPER_ADMIN
        self.is_staff = is_super_admin
        self.is_superuser = is_super_admin
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
