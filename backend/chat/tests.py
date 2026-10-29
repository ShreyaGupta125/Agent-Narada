from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User

from . import grounding, llm
from .models import TITLE_LENGTH, Conversation, Message
from .views import CONVERSATION_NOT_FOUND, MAX_QUESTION_LENGTH

# These tests upload no documents, so every question is answered
# "not found" without asking the language model.


class ChatApiTests(TestCase):
    def ask(self, question, client=None, **extra):
        return (client or self.client).post(
            "/api/chat/", {"question": question}, content_type="application/json", **extra
        )

    def log_in_as(self, role):
        user = User.objects.create_user(username=role.lower(), role=role)
        self.client.force_login(user)
        return user

    def test_anonymous_visitor_is_refused(self):
        self.assertEqual(self.ask("What is the attendance policy?").status_code, 403)

    def test_students_and_staff_can_chat(self):
        for role in (Role.STUDENT, Role.TEACHING_STAFF, Role.NON_TEACHING_STAFF):
            with self.subTest(role=role):
                self.log_in_as(role)
                response = self.ask("What is the attendance policy?")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["answer"])
                self.assertEqual(response.json()["sources"], [])

    def test_super_admin_and_admin_have_no_chatbot(self):
        # Sending the request directly, without the page, is refused as well.
        for role in (Role.SUPER_ADMIN, Role.ADMIN):
            with self.subTest(role=role):
                self.log_in_as(role)
                response = self.ask("What is the attendance policy?")
                self.assertEqual(response.status_code, 403)
                self.assertNotIn("answer", response.json())

    def test_deactivated_user_is_refused(self):
        user = self.log_in_as(Role.STUDENT)
        user.is_active = False
        user.save()
        self.assertEqual(self.ask("Hello").status_code, 403)

    def test_empty_question_is_refused(self):
        self.log_in_as(Role.STUDENT)
        self.assertEqual(self.ask("   ").status_code, 400)

    def test_question_that_is_too_long_is_refused(self):
        self.log_in_as(Role.STUDENT)
        self.assertEqual(self.ask("a" * (MAX_QUESTION_LENGTH + 1)).status_code, 400)

    def test_body_that_is_not_an_object_is_refused(self):
        self.log_in_as(Role.STUDENT)
        response = self.client.post("/api/chat/", [1, 2], content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_chat_must_be_a_post(self):
        self.log_in_as(Role.STUDENT)
        self.assertEqual(self.client.get("/api/chat/").status_code, 405)

    def test_question_without_csrf_token_is_refused(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(User.objects.create_user(username="asha"))
        self.assertEqual(self.ask("Hello", client=strict_client).status_code, 403)

    def test_question_with_csrf_token_is_accepted(self):
        strict_client = Client(enforce_csrf_checks=True)
        strict_client.force_login(User.objects.create_user(username="asha"))
        strict_client.get("/")  # the chat page sets the csrftoken cookie
        token = strict_client.cookies["csrftoken"].value
        response = self.ask("Hello", client=strict_client, headers={"X-CSRFToken": token})
        self.assertEqual(response.status_code, 200)


def days_ago(days):
    return timezone.now() - timedelta(days=days)


def add_message(conversation, text, when, sender=Message.Sender.USER):
    """Store a message with a chosen timestamp, as if written back then."""
    return Message.objects.create(conversation=conversation, sender=sender, text=text, created_at=when)


@override_settings(CHAT_RETENTION_DAYS=7)
class ChatHistoryTestCase(TestCase):
    """Two students, Asha and Ravi, and the Admin and Super Admin."""

    def setUp(self):
        self.asha = User.objects.create_user(username="asha", role=Role.STUDENT)
        self.ravi = User.objects.create_user(username="ravi", role=Role.STUDENT)

    def ask(self, user, question, conversation_id=None):
        self.client.force_login(user)
        body = {"question": question}
        if conversation_id is not None:
            body["conversation_id"] = conversation_id
        return self.client.post("/api/chat/", body, content_type="application/json")

    def conversation_of(self, user, title="Old chat", when=None):
        """A conversation with one question and one answer, written at `when`."""
        when = when or timezone.now()
        conversation = Conversation.objects.create(user=user, title=title, created_at=when, updated_at=when)
        add_message(conversation, title, when)
        add_message(conversation, "An answer.", when, sender=Message.Sender.ASSISTANT)
        return conversation


class SavingChatsTests(ChatHistoryTestCase):
    def test_a_question_and_its_answer_are_saved_in_a_new_conversation(self):
        response = self.ask(self.asha, "What is the attendance policy?")

        conversation = Conversation.objects.get()
        self.assertEqual(response.json()["conversation_id"], conversation.pk)
        self.assertEqual(conversation.user, self.asha)
        self.assertEqual(conversation.title, "What is the attendance policy?")

        question, answer = conversation.messages.all()
        self.assertEqual((question.sender, question.text), ("user", "What is the attendance policy?"))
        self.assertEqual((answer.sender, answer.text), ("assistant", grounding.NOT_FOUND))
        self.assertIsNotNone(question.created_at)

    def test_the_answers_sources_are_saved_with_it(self):
        sources = [{"document_id": 3, "title": "Attendance Policy", "page": 2}]
        with mock.patch("chat.views.build_answer", return_value=("It is 75%.", sources)):
            self.ask(self.asha, "What is the attendance policy?")
        answer = Message.objects.get(sender=Message.Sender.ASSISTANT)
        self.assertEqual(answer.text, "It is 75%.")
        self.assertEqual(answer.sources, sources)

    def test_a_long_first_question_is_shortened_for_the_title(self):
        self.ask(self.asha, "What are the hostel rules " + "for students " * 20)
        title = Conversation.objects.get().title
        self.assertLessEqual(len(title), TITLE_LENGTH + 4)
        self.assertTrue(title.endswith(" ..."))

    def test_continuing_adds_to_the_same_conversation(self):
        first = self.ask(self.asha, "What is the hostel fee?").json()["conversation_id"]
        second = self.ask(self.asha, "What is the library fine?", conversation_id=first).json()["conversation_id"]

        self.assertEqual(first, second)
        self.assertEqual(Conversation.objects.count(), 1)
        texts = [m.text for m in Conversation.objects.get().messages.filter(sender="user")]
        self.assertEqual(texts, ["What is the hostel fee?", "What is the library fine?"])

    def test_without_a_conversation_id_a_new_conversation_starts(self):
        self.ask(self.asha, "What is the hostel fee?")
        self.ask(self.asha, "When are the exams?")
        self.assertEqual(Conversation.objects.filter(user=self.asha).count(), 2)

    def test_a_conversation_id_that_is_not_a_number_is_refused(self):
        for bad in ("12", True, 1.5, [1]):
            with self.subTest(bad=bad):
                self.assertEqual(self.ask(self.asha, "Hi", conversation_id=bad).status_code, 400)

    def test_nothing_is_saved_when_the_model_is_not_running(self):
        error = llm.LLMUnavailable("connection refused")
        with mock.patch("chat.views.build_answer", side_effect=error), self.assertLogs("chat.views", "ERROR"):
            response = self.ask(self.asha, "What is the attendance policy?")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(Conversation.objects.count(), 0)
        self.assertEqual(Message.objects.count(), 0)


class PrivacyTests(ChatHistoryTestCase):
    """One user can never read, add to or change another user's history."""

    def test_the_list_holds_only_the_users_own_conversations(self):
        self.conversation_of(self.asha, "Asha's chat")
        self.conversation_of(self.ravi, "Ravi's chat")

        self.client.force_login(self.asha)
        titles = [c["title"] for c in self.client.get("/api/chat/conversations/").json()]
        self.assertEqual(titles, ["Asha's chat"])

    def test_another_users_conversation_cannot_be_opened(self):
        ravis = self.conversation_of(self.ravi, "Ravi's chat")

        self.client.force_login(self.asha)
        response = self.client.get(f"/api/chat/conversations/{ravis.pk}/")
        # 404, not 403: Asha cannot even learn that the conversation exists.
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Ravi's chat", status_code=404)

    def test_another_users_conversation_cannot_be_added_to(self):
        ravis = self.conversation_of(self.ravi, "Ravi's chat")

        response = self.ask(self.asha, "Sneaky question", conversation_id=ravis.pk)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], CONVERSATION_NOT_FOUND)
        self.assertEqual(ravis.messages.count(), 2)  # unchanged
        self.assertFalse(Message.objects.filter(text="Sneaky question").exists())

    def test_history_cannot_be_edited_through_the_api(self):
        own = self.conversation_of(self.asha)
        self.client.force_login(self.asha)
        url = f"/api/chat/conversations/{own.pk}/"
        for method in (self.client.put, self.client.patch):
            with self.subTest(method=method.__name__):
                self.assertEqual(method(url).status_code, 405)
        self.assertEqual(own.messages.count(), 2)

    def test_admin_super_admin_and_visitors_cannot_read_any_history(self):
        asha_chat = self.conversation_of(self.asha)
        urls = ("/api/chat/conversations/", f"/api/chat/conversations/{asha_chat.pk}/")

        for role in (Role.ADMIN, Role.SUPER_ADMIN):
            self.client.force_login(User.objects.create_user(username=role.lower(), role=role))
            for url in urls:
                with self.subTest(role=role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

        self.client.logout()
        for url in urls:
            with self.subTest(role="visitor", url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_deleting_an_account_deletes_only_its_own_history(self):
        self.conversation_of(self.asha)
        ravis = self.conversation_of(self.ravi)

        self.asha.delete()

        self.assertEqual(list(Conversation.objects.all()), [ravis])
        self.assertEqual(Message.objects.count(), 2)  # only Ravi's two messages remain


class ReadingHistoryTests(ChatHistoryTestCase):
    def test_a_conversation_opens_with_its_messages_oldest_first(self):
        conversation = Conversation.objects.create(user=self.asha, title="Fees")
        add_message(conversation, "First", days_ago(2))
        add_message(conversation, "Second", days_ago(1))

        self.client.force_login(self.asha)
        data = self.client.get(f"/api/chat/conversations/{conversation.pk}/").json()

        self.assertEqual(data["title"], "Fees")
        self.assertEqual([m["text"] for m in data["messages"]], ["First", "Second"])
        self.assertEqual(set(data["messages"][0]), {"id", "sender", "text", "sources", "created_at"})

    def test_newest_conversation_comes_first(self):
        self.conversation_of(self.asha, "Older", when=days_ago(3))
        self.conversation_of(self.asha, "Newer", when=days_ago(1))

        self.client.force_login(self.asha)
        titles = [c["title"] for c in self.client.get("/api/chat/conversations/").json()]
        self.assertEqual(titles, ["Newer", "Older"])


class RetentionTests(ChatHistoryTestCase):
    """Messages older than 7 days are no longer shown, even before the
    automatic cleanup has deleted them."""

    def test_messages_older_than_seven_days_are_not_shown(self):
        conversation = Conversation.objects.create(user=self.asha, title="Mixed")
        add_message(conversation, "Eight days old", days_ago(8))
        add_message(conversation, "Six days old", days_ago(6))

        self.client.force_login(self.asha)
        data = self.client.get(f"/api/chat/conversations/{conversation.pk}/").json()
        self.assertEqual([m["text"] for m in data["messages"]], ["Six days old"])

    def test_a_conversation_with_only_expired_messages_is_gone(self):
        expired = self.conversation_of(self.asha, "Expired", when=days_ago(8))

        self.client.force_login(self.asha)
        self.assertEqual(self.client.get("/api/chat/conversations/").json(), [])
        self.assertEqual(self.client.get(f"/api/chat/conversations/{expired.pk}/").status_code, 404)
        self.assertEqual(self.ask(self.asha, "More?", conversation_id=expired.pk).status_code, 404)

    def test_a_message_just_inside_the_period_is_still_shown(self):
        self.conversation_of(self.asha, "Almost a week", when=days_ago(7) + timedelta(minutes=1))

        self.client.force_login(self.asha)
        titles = [c["title"] for c in self.client.get("/api/chat/conversations/").json()]
        self.assertEqual(titles, ["Almost a week"])


class DeletingHistoryTests(ChatHistoryTestCase):
    """Users can delete one of their conversations, or all of them, and
    never anyone else's."""

    def delete_one(self, user, conversation_id):
        self.client.force_login(user)
        return self.client.delete(f"/api/chat/conversations/{conversation_id}/")

    def clear_all(self, user, body=None):
        self.client.force_login(user)
        return self.client.delete("/api/chat/conversations/", body or {}, content_type="application/json")

    def test_deleting_a_conversation_removes_it_and_its_messages(self):
        first = self.conversation_of(self.asha, "First")
        second = self.conversation_of(self.asha, "Second")

        self.assertEqual(self.delete_one(self.asha, first.pk).status_code, 204)

        self.assertFalse(Conversation.objects.filter(pk=first.pk).exists())
        self.assertFalse(Message.objects.filter(conversation_id=first.pk).exists())  # no orphans
        self.assertEqual(list(Conversation.objects.filter(user=self.asha)), [second])

    def test_a_deleted_conversation_can_no_longer_be_opened_or_continued(self):
        chat = self.conversation_of(self.asha)
        self.delete_one(self.asha, chat.pk)

        self.assertEqual(self.client.get(f"/api/chat/conversations/{chat.pk}/").status_code, 404)
        self.assertEqual(self.client.get("/api/chat/conversations/").json(), [])
        self.assertEqual(self.ask(self.asha, "What is the hostel fee?", conversation_id=chat.pk).status_code, 404)

    def test_another_users_conversation_cannot_be_deleted(self):
        ravis = self.conversation_of(self.ravi, "Ravi's chat")

        response = self.delete_one(self.asha, ravis.pk)

        self.assertEqual(response.status_code, 404)  # as if it did not exist
        self.assertEqual(Conversation.objects.get(pk=ravis.pk).messages.count(), 2)

    def test_an_unknown_conversation_gives_404(self):
        self.assertEqual(self.delete_one(self.asha, 999999).status_code, 404)

    def test_clearing_all_history_needs_an_explicit_confirmation(self):
        self.conversation_of(self.asha)
        for body in [None, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}]:
            with self.subTest(body=body):
                response = self.clear_all(self.asha, body)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Conversation.objects.filter(user=self.asha).count(), 1)  # nothing deleted

    def test_clearing_all_history_deletes_only_the_users_own_conversations(self):
        self.conversation_of(self.asha, "One")
        self.conversation_of(self.asha, "Two", when=days_ago(9))  # an expired one goes too
        ravis = self.conversation_of(self.ravi, "Ravi's chat")

        response = self.clear_all(self.asha, {"confirm": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"deleted_conversations": 2})
        self.assertFalse(Conversation.objects.filter(user=self.asha).exists())
        self.assertEqual(Message.objects.filter(conversation__user=self.asha).count(), 0)
        self.assertEqual(list(Conversation.objects.all()), [ravis])
        self.assertEqual(ravis.messages.count(), 2)

    def test_clearing_an_empty_history_is_fine(self):
        response = self.clear_all(self.asha, {"confirm": True})
        self.assertEqual(response.json(), {"deleted_conversations": 0})

    def test_admin_super_admin_and_visitors_cannot_delete_any_history(self):
        chat = self.conversation_of(self.asha)
        for role in (Role.ADMIN, Role.SUPER_ADMIN):
            user = User.objects.create_user(username=role.lower(), role=role)
            with self.subTest(role=role):
                self.assertEqual(self.delete_one(user, chat.pk).status_code, 403)
                self.assertEqual(self.clear_all(user, {"confirm": True}).status_code, 403)

        self.client.logout()
        self.assertEqual(self.client.delete(f"/api/chat/conversations/{chat.pk}/").status_code, 403)
        self.assertTrue(Conversation.objects.filter(pk=chat.pk).exists())
