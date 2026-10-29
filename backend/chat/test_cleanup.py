"""Tests for the automatic deletion of chat history older than 7 days
(chat/models.py: delete_expired_chats, and the delete_old_chats command)."""

from datetime import datetime, timedelta
from io import StringIO
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User

from .models import Conversation, Message, delete_expired_chats

INDIA = ZoneInfo("Asia/Kolkata")


def days_ago(days, minutes=0):
    return timezone.now() - timedelta(days=days, minutes=minutes)


@override_settings(CHAT_RETENTION_DAYS=7)
class CleanupTests(TestCase):
    def setUp(self):
        self.asha = User.objects.create_user(username="asha", role=Role.STUDENT)
        self.ravi = User.objects.create_user(username="ravi", role=Role.TEACHING_STAFF)

    def chat(self, user, *exchanges):
        """A conversation of (question, answer, when) exchanges."""
        conversation = Conversation.objects.create(user=user, title=exchanges[0][0])
        for question, answer, when in exchanges:
            Message.objects.create(conversation=conversation, sender="user", text=question, created_at=when)
            Message.objects.create(conversation=conversation, sender="assistant", text=answer, created_at=when)
        return conversation

    def texts(self):
        return set(Message.objects.values_list("text", flat=True))

    def test_the_requirement_example(self):
        # A message sent on 1 October at 10:00 is deleted once it is more
        # than 7 days old. One sent on 12 October stays until it is too.
        oct_1 = datetime(2026, 10, 1, 10, 0, tzinfo=INDIA)
        oct_12 = datetime(2026, 10, 12, 10, 0, tzinfo=INDIA)
        self.chat(self.asha, ("Oct 1 question", "Oct 1 answer", oct_1))
        self.chat(self.asha, ("Oct 12 question", "Oct 12 answer", oct_12))

        # Cleanup on 8 October at 09:59: nothing is 7 days old yet.
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 8, 9, 59, tzinfo=INDIA)):
            delete_expired_chats()
        self.assertEqual(len(self.texts()), 4)

        # Cleanup on 13 October: the 1 October messages are gone.
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 13, 12, 0, tzinfo=INDIA)):
            delete_expired_chats()
        self.assertEqual(self.texts(), {"Oct 12 question", "Oct 12 answer"})

        # Cleanup on 19 October at 10:01: the 12 October messages go too.
        with mock.patch("django.utils.timezone.now", return_value=datetime(2026, 10, 19, 10, 1, tzinfo=INDIA)):
            delete_expired_chats()
        self.assertEqual(self.texts(), set())

    def test_messages_older_than_seven_days_are_deleted_and_newer_ones_kept(self):
        self.chat(
            self.asha,
            ("Old question", "Old answer", days_ago(8)),
            ("New question", "New answer", days_ago(1)),
        )

        messages, conversations = delete_expired_chats()

        self.assertEqual((messages, conversations), (2, 0))
        self.assertEqual(self.texts(), {"New question", "New answer"})

    def test_the_limit_is_exactly_seven_days(self):
        self.chat(self.asha, ("Just expired", "a", days_ago(7, minutes=1)))
        self.chat(self.asha, ("Still kept", "b", days_ago(6, minutes=1439)))

        delete_expired_chats()

        self.assertEqual(self.texts(), {"Still kept", "b"})

    def test_a_conversation_whose_messages_all_expired_is_deleted(self):
        old = self.chat(self.asha, ("Old question", "Old answer", days_ago(9)))

        messages, conversations = delete_expired_chats()

        self.assertEqual((messages, conversations), (2, 1))
        self.assertFalse(Conversation.objects.filter(pk=old.pk).exists())

    def test_nothing_is_left_behind(self):
        self.chat(self.asha, ("Old", "Old answer", days_ago(9)))
        self.chat(self.ravi, ("Mixed old", "x", days_ago(10)), ("Mixed new", "y", days_ago(2)))

        delete_expired_chats()

        # No conversation without messages, and no message without a conversation.
        self.assertFalse(Conversation.objects.filter(messages__isnull=True).exists())
        self.assertEqual(
            Message.objects.count(),
            Message.objects.filter(conversation__in=Conversation.objects.all()).count(),
        )

    def test_a_title_made_from_an_expired_question_is_replaced(self):
        conversation = self.chat(
            self.asha,
            ("Expired first question", "a", days_ago(8)),
            ("Newer question", "b", days_ago(1)),
        )

        delete_expired_chats()

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Newer question")
        # The expired text is gone from every table.
        self.assertFalse(Message.objects.filter(text__contains="Expired first").exists())
        self.assertFalse(Conversation.objects.filter(title__contains="Expired first").exists())

    def test_one_users_expired_chats_do_not_affect_another_users_newer_chats(self):
        self.chat(self.asha, ("Asha old", "a", days_ago(8)))
        ravis = self.chat(self.ravi, ("Ravi new", "r", days_ago(1)))

        delete_expired_chats()

        self.assertEqual(self.texts(), {"Ravi new", "r"})
        self.client.force_login(self.ravi)
        listed = self.client.get("/api/chat/conversations/").json()
        self.assertEqual([c["id"] for c in listed], [ravis.pk])
        self.assertEqual(len(self.client.get(f"/api/chat/conversations/{ravis.pk}/").json()["messages"]), 2)

    def test_every_chatbot_role_follows_the_same_rule(self):
        for role in (Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF):
            user = User.objects.create_user(username=f"user_{role}", role=role)
            self.chat(user, (f"{role} old", "a", days_ago(8)), (f"{role} new", "b", days_ago(1)))

        delete_expired_chats()

        kept = {text for text in self.texts() if text not in {"a", "b"}}
        self.assertEqual(kept, {"STUDENT new", "TEACHING_STAFF new", "NON_TEACHING_STAFF new"})

    def test_running_it_again_changes_nothing(self):
        self.chat(self.asha, ("Old", "a", days_ago(8)), ("New", "b", days_ago(1)))

        self.assertEqual(delete_expired_chats(), (2, 0))
        self.assertEqual(delete_expired_chats(), (0, 0))
        self.assertEqual(self.texts(), {"New", "b"})

    def test_an_empty_database_is_fine(self):
        self.assertEqual(delete_expired_chats(), (0, 0))


@override_settings(CHAT_RETENTION_DAYS=7)
class CommandTests(TestCase):
    def test_the_command_deletes_and_reports(self):
        user = User.objects.create_user(username="asha")
        conversation = Conversation.objects.create(user=user, title="Old")
        Message.objects.create(conversation=conversation, sender="user", text="Old", created_at=days_ago(8))

        output = StringIO()
        call_command("delete_old_chats", stdout=output)

        self.assertEqual(
            output.getvalue().strip(),
            "Deleted 1 message(s) and 1 conversation(s) older than 7 days.",
        )
        self.assertEqual(Message.objects.count(), 0)
