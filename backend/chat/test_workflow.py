"""One complete workflow through the real API, step by step, the way
people use Agent Narada:

  Admin uploads -> stays pending (not answered from) -> Super Admin
  approves -> student asks -> answer with its source -> follow-up ->
  teacher is not given the student document -> student deletes the chat
  -> the 7-day cleanup removes old chats.

Only the language model is replaced (by FakeModel), so no llama-server
is needed; everything else is the real system.
"""

import json
import shutil
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from accounts.models import Role, User

from . import grounding, scope
from .models import Conversation, Message

MEDIA = tempfile.mkdtemp()

HOSTEL_RULES = b"""HOSTEL RULES

1. Gate timings
The hostel gates close at 10:00 pm every night.

2. Mess timings
Dinner is served from 7:30 pm to 9:30 pm.
"""


class FakeModel:
    """Stands in for Qwen: gives the prepared reply for each kind of request."""

    def __init__(self, answer="", rewrite=""):
        self.answer, self.rewrite, self.calls = answer, rewrite, 0

    def __call__(self, messages, json_schema=None):
        self.calls += 1
        if json_schema == scope.REWRITE_SCHEMA:
            return json.dumps({"question": self.rewrite})
        if json_schema == scope.CLASSIFY_SCHEMA:
            return json.dumps({"topic": "university"})
        return json.dumps({"answer": self.answer, "evidence": [], "status": "answered", "missing": ""})


@override_settings(MEDIA_ROOT=MEDIA)
class CompleteWorkflowTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def client_for(self, role, username):
        client = Client()
        client.force_login(User.objects.create_user(username=username, role=role))
        return client

    def ask(self, client, question, model, conversation_id=None):
        body = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        with mock.patch("chat.llm.generate", side_effect=model), mock.patch.object(grounding.logger, "warning"):
            return client.post("/api/chat/", body, content_type="application/json").json()

    def test_the_whole_journey(self):
        admin = self.client_for(Role.ADMIN, "meera_admin")
        super_admin = self.client_for(Role.SUPER_ADMIN, "director")
        student = self.client_for(Role.STUDENT, "asha")
        teacher = self.client_for(Role.TEACHING_STAFF, "ravi")

        # 1. The Admin uploads the hostel rules for students. The text is
        #    read and indexed at once, but the document waits for approval.
        upload = admin.post(
            "/api/documents/",
            {"title": "Hostel Rules", "file": SimpleUploadedFile("hostel.txt", HOSTEL_RULES), "for_students": "true"},
        ).json()
        self.assertEqual(upload["status"], "PENDING")
        self.assertTrue(upload["processed"])

        # 2. While it is pending, students get no answer from it, and the
        #    model is not even asked.
        model = FakeModel(answer="10:00 pm")
        reply = self.ask(student, "When do the hostel gates close?", model)
        self.assertEqual(reply["answer"], grounding.NOT_FOUND)
        self.assertEqual(model.calls, 0)

        # 3. The Admin cannot approve their own upload; the Super Admin can.
        self.assertEqual(admin.post(f"/api/documents/{upload['id']}/approve/").status_code, 403)
        self.assertEqual(super_admin.post(f"/api/documents/{upload['id']}/approve/").json()["status"], "APPROVED")

        # 4. Now the student gets the answer, with its source and section.
        reply = self.ask(student, "When do the hostel gates close?", FakeModel(answer="10:00 pm every night"))
        self.assertEqual(reply["answer"], "10:00 pm every night")
        self.assertEqual(reply["sources"][0]["title"], "Hostel Rules")
        self.assertEqual(reply["sources"][0]["section"], "1. Gate timings")
        conversation_id = reply["conversation_id"]

        # 5. A follow-up in the same conversation.
        follow_up = self.ask(
            student,
            "and when is dinner?",
            FakeModel(rewrite="When is dinner served in the hostel mess?", answer="7:30 pm to 9:30 pm"),
            conversation_id,
        )
        self.assertEqual(follow_up["answer"], "7:30 pm to 9:30 pm")
        self.assertEqual(follow_up["sources"][0]["section"], "2. Mess timings")

        # 6. The document is for students only: a teacher gets no answer.
        model = FakeModel(answer="10:00 pm")
        reply = self.ask(teacher, "When do the hostel gates close?", model)
        self.assertEqual(reply["answer"], grounding.NOT_FOUND)
        self.assertEqual(model.calls, 0)

        # 7. Small talk and off-topic questions are handled without documents.
        self.assertTrue(self.ask(student, "Thank you!", FakeModel())["answer"].startswith("You're welcome"))
        self.assertEqual(self.ask(student, "Who won the cricket match?", FakeModel())["answer"], scope.OFF_TOPIC)

        # 8. The student sees their conversations, and only theirs.
        listed = student.get("/api/chat/conversations/").json()
        # Step 2's "couldn't find" reply, the hostel chat (with its
        # follow-up), "Thank you!" and the cricket question.
        self.assertEqual(len(listed), 4)
        self.assertEqual(teacher.get(f"/api/chat/conversations/{conversation_id}/").status_code, 404)

        # 9. The student deletes the hostel conversation; its messages go too.
        self.assertEqual(student.delete(f"/api/chat/conversations/{conversation_id}/").status_code, 204)
        self.assertFalse(Message.objects.filter(conversation_id=conversation_id).exists())

        # 10. Eight days later, the automatic cleanup removes everything left.
        Message.objects.update(created_at=timezone.now() - timedelta(days=8))
        call_command("delete_old_chats", stdout=StringIO())
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(Message.objects.exists())
