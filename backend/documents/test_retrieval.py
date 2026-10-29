"""Tests for document processing (file -> passages) and retrieval (question -> passages)."""

import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import Role
from chat import llm
from chat.grounding import NOT_FOUND, PARTIAL_NOTE
from chat import scope
from chat.scope import OFF_TOPIC
from chat.views import MODEL_NOT_RUNNING

from .models import Document, Passage
from .processing import IngestionError, process_document
from .retrieval import question_parts, search, uncovered_parts
from .tests import DocumentTestCase, make_pdf, make_user
from .text import keywords


def add_document(uploader, title, content, filename="document.txt", **access):
    """Store a document and process it, as the upload view does."""
    if isinstance(content, str):
        content = content.encode()
    document = Document.objects.create(
        title=title,
        file=SimpleUploadedFile(filename, content),
        uploaded_by=uploader,
        **access,
    )
    return process_document(document)


class KeywordTests(DocumentTestCase):
    def test_keywords_are_lower_case_without_punctuation_or_common_words(self):
        self.assertEqual(
            keywords("What is the Attendance Policy?"), ["attendance", "policy"]
        )

    def test_plurals_are_reduced_so_they_match_the_singular(self):
        self.assertEqual(keywords("policies fees classes courses"), ["policy", "fee", "class", "course"])

    def test_exam_and_examination_are_the_same_word(self):
        self.assertEqual(keywords("exam exams examination examinations"), ["exam"] * 4)

    def test_words_that_only_shape_a_question_are_dropped(self):
        self.assertEqual(keywords("What is the last date? Is attendance required?"), ["date", "attendance"])

    def test_ing_endings_and_everyday_words_match_the_documents(self):
        self.assertEqual(keywords("checking borrowing timings"), ["check", "borrow", "tim"])
        self.assertEqual(keywords("check borrow timing"), ["check", "borrow", "tim"])
        self.assertEqual(keywords("visit curfew criteria requirement"), ["visitor", "gate", "minimum", "minimum"])

    def test_words_that_only_look_plural_are_left_alone(self):
        self.assertEqual(keywords("campus thesis class"), ["campus", "thesis", "class"])


class ProcessingTests(DocumentTestCase):
    def test_text_file_becomes_passages_with_keywords(self):
        document = add_document(self.admin, "Hostel", "Hostel gates close at ten in the evening.")
        self.assertEqual(document.passage_count, 1)
        self.assertIsNotNone(document.processed_at)

        passage = document.passages.get()
        self.assertEqual(passage.number, 1)
        self.assertIsNone(passage.page)
        self.assertEqual(passage.text, "Hostel gates close at ten in the evening.")
        # The passage's own keywords, then the document title's.
        # "evening" -> "even": the -ing ending is removed, in documents and questions alike.
        self.assertEqual(passage.terms, " hostel gate close ten even hostel ")

    def test_pdf_text_is_read_page_by_page(self):
        pdf = make_pdf(["Attendance must be seventy five percent.", "Fees are paid each semester."])
        document = add_document(self.admin, "Rules", pdf, filename="rules.pdf")

        self.assertEqual(document.passage_count, 2)
        pages = {passage.page: passage.text for passage in document.passages.all()}
        self.assertIn("Attendance", pages[1])
        self.assertIn("Fees", pages[2])

    def test_file_with_no_text_is_not_processed(self):
        with self.assertRaises(IngestionError):
            add_document(self.admin, "Empty", "   ")
        document = Document.objects.get(title="Empty")
        self.assertIsNone(document.processed_at)
        self.assertEqual(document.passages.count(), 0)

    def test_damaged_pdf_is_not_processed(self):
        with self.assertRaises(IngestionError):
            add_document(self.admin, "Damaged", b"%PDF-1.4 not really", filename="damaged.pdf")
        self.assertIsNone(Document.objects.get(title="Damaged").processed_at)

    def test_processing_again_replaces_the_old_passages(self):
        document = add_document(self.admin, "Hostel", "Hostel gates close at ten.")
        process_document(document)
        self.assertEqual(document.passages.count(), 1)

    def test_deleting_a_document_deletes_its_passages(self):
        document = add_document(self.admin, "Hostel", "Hostel gates close at ten.")
        document.delete()
        self.assertEqual(Passage.objects.count(), 0)

    def test_upload_through_the_api_processes_the_file(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            "/api/documents/",
            {
                "title": "Hostel Rules",
                "file": SimpleUploadedFile("hostel.txt", b"Hostel gates close at ten."),
                "for_students": "true",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["passage_count"], 1)
        self.assertEqual(Passage.objects.count(), 1)


class RetrievalTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.teacher = make_user(Role.TEACHING_STAFF)
        self.staff = make_user(Role.NON_TEACHING_STAFF)

    def titles_found(self, user, question):
        return [passage.document.title for passage in search(user, question)]

    # ----- permission comes first -----

    def test_each_role_finds_only_documents_opened_to_it(self):
        add_document(self.super_admin, "Student Leave", "Leave rules for students.", for_students=True)
        add_document(self.super_admin, "Faculty Leave", "Leave rules for faculty.", for_teaching_staff=True)
        add_document(self.super_admin, "Staff Leave", "Leave rules for office staff.", for_non_teaching_staff=True)

        self.assertEqual(self.titles_found(self.student, "leave rules"), ["Student Leave"])
        self.assertEqual(self.titles_found(self.teacher, "leave rules"), ["Faculty Leave"])
        self.assertEqual(self.titles_found(self.staff, "leave rules"), ["Staff Leave"])

    def test_asking_for_another_roles_document_by_name_finds_nothing(self):
        add_document(self.super_admin, "Faculty Salary", "Faculty salary bands and increments.", for_teaching_staff=True)
        self.assertEqual(self.titles_found(self.student, "faculty salary bands increments"), [])

    def test_pending_document_is_not_searchable_until_approved(self):
        document = add_document(self.admin, "Hostel", "Hostel gates close at ten.", for_students=True)
        self.assertEqual(self.titles_found(self.student, "hostel gates"), [])

        document.approve(self.super_admin)
        self.assertEqual(self.titles_found(self.student, "hostel gates"), ["Hostel"])

    def test_rejected_document_is_not_searchable(self):
        document = add_document(self.admin, "Hostel", "Hostel gates close at ten.", for_students=True)
        document.approve(self.super_admin)
        document.reject(self.super_admin, "Out of date")
        self.assertEqual(self.titles_found(self.student, "hostel gates"), [])

    def test_super_admin_admin_and_deactivated_users_find_nothing(self):
        add_document(self.super_admin, "Hostel", "Hostel gates close at ten.", for_students=True)
        self.student.is_active = False
        self.student.save()
        for user in (self.super_admin, self.admin, self.student):
            with self.subTest(role=user.role):
                self.assertEqual(search(user, "hostel gates"), [])

    # ----- ranking -----

    def test_best_matching_passage_comes_first(self):
        add_document(self.super_admin, "Library", "The library opens at nine every morning.", for_students=True)
        add_document(self.super_admin, "Attendance", "Attendance below seventy five percent bars the exam.", for_students=True)
        add_document(self.super_admin, "Exams", "The exam timetable is published each semester.", for_students=True)

        found = self.titles_found(self.student, "What attendance is needed for the exam?")
        self.assertEqual(found[0], "Attendance")
        self.assertNotIn("Library", found)

    def test_a_rare_word_outweighs_a_common_one(self):
        for number in range(5):
            add_document(self.super_admin, f"General {number}", "University rules and notices.", for_students=True)
        add_document(self.super_admin, "Scholarship", "University scholarship criteria.", for_students=True)

        self.assertEqual(self.titles_found(self.student, "university scholarship")[0], "Scholarship")

    def test_plural_in_the_question_matches_singular_in_the_document(self):
        add_document(self.super_admin, "Fee", "The hostel fee is due in July.", for_students=True)
        self.assertEqual(self.titles_found(self.student, "hostel fees"), ["Fee"])

    def test_one_stray_word_in_common_is_not_a_match(self):
        add_document(
            self.super_admin,
            "Attendance",
            "Medical leave is counted when attendance is calculated.",
            for_students=True,
        )
        # Shares only the word "leave" with the passage: 1 keyword out of 5.
        question = "How many days of casual leave and sabbatical do faculty get?"
        self.assertEqual(search(self.student, question), [])
        # A question really about the passage still finds it.
        self.assertEqual(self.titles_found(self.student, "Is medical leave counted?"), ["Attendance"])

    def test_question_with_no_matching_words_finds_nothing(self):
        add_document(self.super_admin, "Hostel", "Hostel gates close at ten.", for_students=True)
        self.assertEqual(search(self.student, "cricket tournament schedule"), [])

    def test_question_of_only_common_words_finds_nothing(self):
        add_document(self.super_admin, "Hostel", "What is the rule for this?", for_students=True)
        self.assertEqual(search(self.student, "what is the"), [])

    # ----- relevance threshold -----

    def test_a_passage_sharing_only_a_common_word_is_dropped(self):
        for number, topic in enumerate(["library books", "exam dates", "fee payment", "sports timings", "bus routes"]):
            add_document(self.super_admin, f"Notice {number}", f"Students: {topic}.", for_students=True)
        # "student" is in every passage; "hostel" and "curfew" are in none.
        self.assertEqual(search(self.student, "student hostel curfew"), [])

    def test_a_much_weaker_match_than_the_best_is_dropped(self):
        add_document(self.super_admin, "Fees", "The hostel fee is Rs 95,000 per semester.", for_students=True)
        add_document(self.super_admin, "Wardens", "The hostel warden is on extension 4100.", for_students=True)
        self.assertEqual(self.titles_found(self.student, "What is the hostel fee?"), ["Fees"])

    def test_each_part_of_a_question_is_searched(self):
        add_document(self.super_admin, "Fees", "The late fee is Rs 100 per day.", for_students=True)
        add_document(self.super_admin, "Library", "The library opens at 8 am.", for_students=True)
        found = self.titles_found(self.student, "What is the late fee, and when does the library open?")
        self.assertEqual(sorted(found), ["Fees", "Library"])

    def test_the_part_no_document_covers_is_reported(self):
        add_document(self.super_admin, "Fees", "The late fee is Rs 100 per day.", for_students=True)
        question = "What is the late fee, and is there a discount for early payment?"
        self.assertEqual(question_parts(question), ["What is the late fee", "is there a discount for early payment"])
        self.assertEqual(uncovered_parts(self.student, question), ["is there a discount for early payment"])

    def test_exam_finds_examination(self):
        add_document(self.super_admin, "Rules", "Bring the ID card to every examination.", for_students=True)
        self.assertEqual(self.titles_found(self.student, "What do I bring to the exam?"), ["Rules"])

    def test_equally_good_matches_come_in_document_order(self):
        add_document(
            self.super_admin,
            "Attendance Notice",
            "1. Minimum attendance\nStudents need 75% attendance.\n\n"
            "2. Contact\nThe attendance cell answers attendance questions about attendance.",
            for_students=True,
        )
        found = [p.section for p in search(self.student, "attendance rules")]
        self.assertEqual(found[0], "1. Minimum attendance")

    def test_a_word_in_no_document_cannot_outweigh_the_real_topic(self):
        add_document(self.super_admin, "Attendance", "Students need 75% attendance in each course.", for_students=True)
        add_document(self.super_admin, "Library", "The library opens at 8 am.", for_students=True)
        # "eligibility" is in no document: it must not hide the attendance passage.
        self.assertEqual(self.titles_found(self.student, "attendance eligibility"), ["Attendance"])

    def test_result_count_is_limited(self):
        for number in range(6):
            add_document(self.super_admin, f"Notice {number}", "Hostel notice.", for_students=True)
        self.assertEqual(len(search(self.student, "hostel", limit=4)), 4)


def echo_model(messages, json_schema=None):
    """A stand-in for Qwen: it answers with the text of the first passage
    it was given, and quotes it as evidence. The real checks in
    chat/grounding.py still run on this reply."""
    passages = messages[1]["content"].split("\n\n")[1:-1]  # without "Passages:" and the question
    first = passages[0].split("\n", 1)[1]  # without the "[1] Title" label
    return json.dumps({"answer": first, "evidence": [{"passage": 1, "quote": first}], "status": "answered", "missing": ""})


def titles_sent(messages):
    """The document titles of the passages a conversation sent to the model."""
    return [line.split("] ", 1)[1] for line in messages[1]["content"].split("\n") if line.startswith("[")]


class ChatRetrievalTests(DocumentTestCase):
    """The chat API answers from the passages the user's role may read.

    The connection to the model (chat.llm.generate) is replaced by
    echo_model, so these tests run without llama-server and show which
    passages the model would have received.
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch("chat.llm.generate", side_effect=echo_model)
        self.model = patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, question):
        return self.client.post("/api/chat/", {"question": question}, content_type="application/json")

    def test_answer_quotes_the_passage_and_names_its_source(self):
        pdf = make_pdf(["Library timings.", "Attendance must be seventy five percent."])
        add_document(self.super_admin, "Academic Rules", pdf, filename="rules.pdf", for_students=True)

        self.client.force_login(self.student)
        reply = self.ask("What attendance is required?").json()

        self.assertIn("seventy five percent", reply["answer"])
        self.assertEqual(len(reply["sources"]), 1)
        self.assertEqual(reply["sources"][0]["title"], "Academic Rules")
        self.assertEqual(reply["sources"][0]["page"], 2)

    def test_student_cannot_get_a_staff_document_through_the_chat(self):
        add_document(self.super_admin, "Faculty Salary", "The faculty salary band is Rs 50,000.", for_teaching_staff=True)

        self.client.force_login(self.student)
        response = self.ask("What is the faculty salary band?")

        self.assertNotContains(response, "50,000")
        self.assertEqual(response.json()["answer"], NOT_FOUND)
        self.assertEqual(response.json()["sources"], [])
        self.model.assert_not_called()  # the restricted passage never reached the model

    def test_teacher_gets_the_same_document_the_student_was_refused(self):
        add_document(self.super_admin, "Faculty Salary", "The faculty salary band is Rs 50,000.", for_teaching_staff=True)

        self.client.force_login(make_user(Role.TEACHING_STAFF))
        reply = self.ask("What is the faculty salary band?").json()

        self.assertIn("Rs 50,000", reply["answer"])
        self.assertEqual(reply["sources"][0]["title"], "Faculty Salary")

    def test_university_question_with_no_match_says_so_without_asking_the_model(self):
        self.client.force_login(self.student)
        reply = self.ask("What is the hostel curfew on weekends?").json()
        self.assertEqual(reply["answer"], NOT_FOUND)
        self.assertEqual(reply["sources"], [])
        self.model.assert_not_called()

    def test_off_topic_question_gets_the_scope_reply_without_asking_the_model(self):
        add_document(self.super_admin, "Sports", "The cricket ground is behind Block 6.", for_students=True)
        self.client.force_login(self.student)
        reply = self.ask("Who won yesterday's cricket match?").json()
        self.assertEqual(reply["answer"], OFF_TOPIC)
        self.assertEqual(reply["sources"], [])
        self.model.assert_not_called()

    def test_the_model_receives_the_question_and_only_permitted_passages(self):
        add_document(self.super_admin, "Hostel Rules", "Hostel gates close at ten.", for_students=True)
        add_document(self.super_admin, "Staff Hostel", "Staff hostel gates close at midnight.", for_teaching_staff=True)

        self.client.force_login(self.student)
        self.ask("When do hostel gates close?")

        messages = self.model.call_args.args[0]
        self.assertTrue(messages[1]["content"].endswith("Question: When do hostel gates close?"))
        self.assertEqual(titles_sent(messages), ["Hostel Rules"])

    def test_when_the_model_finds_no_answer_no_sources_are_shown(self):
        add_document(self.super_admin, "Hostel Rules", "Hostel gates close at ten.", for_students=True)
        self.model.side_effect = None
        self.model.return_value = json.dumps({"answer": "", "evidence": [], "status": "not_found", "missing": ""})

        self.client.force_login(self.student)
        reply = self.ask("What is the hostel fee?").json()

        self.assertEqual(reply["answer"], NOT_FOUND)
        self.assertEqual(reply["sources"], [])

    def test_an_answer_that_fails_the_checks_is_never_shown(self):
        add_document(self.super_admin, "Hostel Rules", "Hostel gates close at ten.", for_students=True)
        self.model.side_effect = None
        self.model.return_value = json.dumps(
            {"answer": "The hostel fee is Rs 90,000.", "evidence": [], "status": "answered", "missing": ""}
        )

        self.client.force_login(self.student)
        with self.assertLogs("chat.grounding", "WARNING"):
            reply = self.ask("When do hostel gates close and what is the hostel fee?").json()

        self.assertEqual(reply["answer"], NOT_FOUND)
        self.assertNotIn("90,000", str(reply))

    def test_only_the_passage_that_supports_the_answer_is_a_source(self):
        # 240 words: long enough to be cut into several passages of one text file.
        document = add_document(
            self.super_admin, "Hostel Rules", "Hostel gates close at ten. " * 48, for_students=True
        )

        self.client.force_login(self.student)
        reply = self.ask("When do hostel gates close?").json()

        self.assertGreaterEqual(len(titles_sent(self.model.call_args.args[0])), 2)  # several were sent
        self.assertEqual(
            reply["sources"],
            [{"document_id": document.pk, "title": "Hostel Rules", "section": "", "page": None}],
        )

    def test_a_part_of_the_question_no_document_covers_is_named(self):
        add_document(self.super_admin, "Fees", "LATE FEE\n\nA late fee of Rs 100 per day is charged.", for_students=True)

        self.client.force_login(self.student)
        reply = self.ask("What is the late fee, and is there a discount for early payment?").json()

        self.assertIn("Rs 100 per day", reply["answer"])
        self.assertIn(PARTIAL_NOTE + '"is there a discount for early payment"', reply["answer"])

    def test_model_not_running_gives_a_clear_message(self):
        add_document(self.super_admin, "Hostel Rules", "Hostel gates close at ten.", for_students=True)
        self.model.side_effect = llm.LLMUnavailable("connection refused")

        self.client.force_login(self.student)
        with self.assertLogs("chat.views", level="ERROR"):
            response = self.ask("When do hostel gates close?")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], MODEL_NOT_RUNNING)
        # The technical reason stays on the server.
        self.assertNotContains(response, "connection refused", status_code=503)


class FakeModel:
    """A stand-in for Qwen that records every request. It recognises which
    job it is given by the forced reply shape, like the real model's
    replies are shaped by it."""

    def __init__(self, answer="", rewrite="", topic="university"):
        self.answer, self.rewrite, self.topic = answer, rewrite, topic
        self.requests = []

    def __call__(self, messages, json_schema=None):
        self.requests.append(messages)
        if json_schema == scope.REWRITE_SCHEMA:
            return json.dumps({"question": self.rewrite})
        if json_schema == scope.CLASSIFY_SCHEMA:
            return json.dumps({"topic": self.topic})
        return json.dumps({"answer": self.answer, "evidence": [], "status": "answered", "missing": ""})

    def everything_sent(self):
        return json.dumps(self.requests)


class ScopeAndFollowUpChatTests(DocumentTestCase):
    """Step 7 through the chat API: small talk, scope, follow-ups."""

    def setUp(self):
        super().setUp()
        add_document(
            self.super_admin,
            "Fee Structure",
            "HOSTEL FEES\n\nSingle room, with mess: Rs 1,25,000.\nTwin sharing, with mess: Rs 95,000.",
            for_students=True,
        )
        add_document(
            self.super_admin,
            "Faculty Salary",
            "Assistant professor salary: Rs 57,700 per month.",
            for_teaching_staff=True,
        )
        self.client.force_login(self.student)

    def ask(self, model, question, conversation_id=None):
        body = {"question": question}
        if conversation_id:
            body["conversation_id"] = conversation_id
        with mock.patch("chat.llm.generate", side_effect=model), mock.patch("chat.grounding.logger"):
            return self.client.post("/api/chat/", body, content_type="application/json").json()

    def test_a_greeting_is_answered_and_saved_without_search_or_model(self):
        model = FakeModel()
        reply = self.ask(model, "Hello!")
        self.assertTrue(reply["answer"].startswith("Hello! I'm Agent Narada"))
        self.assertEqual(reply["sources"], [])
        self.assertEqual(model.requests, [])
        self.assertTrue(reply["conversation_id"])  # saved in the history like any message

    def test_an_unclear_off_topic_question_gets_the_scope_reply(self):
        model = FakeModel(topic="other")
        reply = self.ask(model, "What is the capital of France?")
        self.assertEqual(reply["answer"], OFF_TOPIC)
        self.assertEqual(len(model.requests), 1)  # only the "university or other?" question

    def test_a_follow_up_is_answered_from_the_row_it_asks_about(self):
        first = self.ask(FakeModel(answer="Rs 1,25,000"), "What is the hostel fee for a single room?")
        self.assertEqual(first["answer"], "Rs 1,25,000")

        model = FakeModel(rewrite="What is the hostel fee for twin sharing?", answer="Rs 95,000")
        reply = self.ask(model, "and for twin sharing?", first["conversation_id"])
        self.assertEqual(reply["answer"], "Rs 95,000")
        self.assertEqual(reply["sources"][0]["title"], "Fee Structure")

    def test_a_follow_up_answered_from_the_earlier_questions_row_is_refused(self):
        first = self.ask(FakeModel(answer="Rs 1,25,000"), "What is the hostel fee for a single room?")
        model = FakeModel(rewrite="What is the hostel fee for a single room and for twin sharing?", answer="Rs 1,25,000")
        reply = self.ask(model, "and for twin sharing?", first["conversation_id"])
        self.assertEqual(reply["answer"], NOT_FOUND)

    def test_a_follow_up_cannot_reach_a_document_the_role_may_not_read(self):
        first = self.ask(FakeModel(answer="Rs 95,000"), "What is the hostel fee for twin sharing?")
        model = FakeModel(rewrite="What is the assistant professor salary?", answer="Rs 57,700 per month")
        reply = self.ask(model, "And what about the assistant professor salary?", first["conversation_id"])

        self.assertEqual(reply["answer"], NOT_FOUND)
        self.assertNotIn("57,700", model.everything_sent())  # the salary passage never reached the model

    def test_only_the_earlier_question_is_given_to_the_rewrite_never_its_answer(self):
        first = self.ask(FakeModel(answer="Rs 1,25,000"), "What is the hostel fee for a single room?")
        model = FakeModel(rewrite="What is the hostel fee for twin sharing?", answer="Rs 95,000")
        self.ask(model, "and for twin sharing?", first["conversation_id"])

        rewrite_request = model.requests[0][1]["content"]
        self.assertIn("What is the hostel fee for a single room?", rewrite_request)
        self.assertNotIn("1,25,000", rewrite_request)

    def test_a_question_with_spelling_mistakes_finds_the_answer(self):
        model = FakeModel(answer="Rs 1,25,000")
        reply = self.ask(model, "wat is hostal fee for singel rom")
        self.assertEqual(reply["answer"], "Rs 1,25,000")
        self.assertEqual(reply["sources"][0]["title"], "Fee Structure")
        # The model was given the corrected question.
        self.assertIn("hostel fee for single", model.requests[0][1]["content"])
        # The user's own words are what is saved in the history.
        history = self.client.get(f"/api/chat/conversations/{reply['conversation_id']}/").json()
        self.assertEqual(history["messages"][0]["text"], "wat is hostal fee for singel rom")
