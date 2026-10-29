from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User

# A serializer is the gatekeeper for incoming JSON: nothing is saved unless
# every field passes. Because these are built from the User model, they
# already know that the username must be unique and that the role must be
# one of the five roles.

ACCOUNT_FIELDS = ["username", "password", "role", "first_name", "last_name", "email", "is_active"]


class UserCreateSerializer(serializers.ModelSerializer):
    """Checks the data sent when the Super Admin creates an account."""

    # write_only: accepted when creating, never sent back in a reply.
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ACCOUNT_FIELDS
        # The role must be chosen deliberately; there is no silent default here.
        extra_kwargs = {"role": {"required": True}}

    def validate_password(self, value):
        # Applies the rules in settings.AUTH_PASSWORD_VALIDATORS
        # (minimum length, not a common password, not only digits).
        validate_password(value)
        return value

    def create(self, validated_data):
        # create_user() stores the password as a hash, never as plain text.
        return User.objects.create_user(**validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    """Checks the data sent when the Super Admin modifies an account.

    Only the fields that are sent are changed. An empty password means
    "keep the current password".
    """

    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ACCOUNT_FIELDS

    def validate_password(self, value):
        if value:
            validate_password(value, user=self.instance)
        return value

    def validate(self, data):
        # A Super Admin must not lock themselves out. Because nobody can
        # demote or deactivate their own account, the system always keeps
        # at least one working Super Admin.
        if self.instance == self.context["request"].user:
            if data.get("role", self.instance.role) != self.instance.role:
                raise serializers.ValidationError(
                    {"role": "You cannot change your own role."}
                )
            if data.get("is_active", True) is False:
                raise serializers.ValidationError(
                    {"is_active": "You cannot deactivate your own account."}
                )
        return data

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)  # stored as a hash
        instance.save()
        return instance
