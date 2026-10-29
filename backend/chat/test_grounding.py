"""Tests for chat/grounding.py: how the model's reply is checked before
any answer reaches the user. No real model is used: each test gives a
prepared reply, written the way Qwen writes them."""

import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from documents.text import keywords

from . import grounding
from .grounding import NOT_FOUND, PARTIAL_NOTE, check_reply


def passage(text, title="Rules", section="", page=None):
    """Something shaped like a Passage, without needing the database."""
    return SimpleNamespace(
        document=SimpleNamespace(title=title),
        section=section,
        page=page,
        text=text,
        terms=" " + " ".join(keywords(text) + keywords(title)) + " ",
    )


def reply(answer, status="answered", evidence=(), missing=""):
    return json.dumps(
        {"answer": answer, "evidence": [{"passage": n, "quote": q} for n, q in evidence], "status": status, "missing": missing}
    )


ATTENDANCE = passage(
    "1. Minimum attendance\nEvery student must attend at least 75% of the classes in each course.",
    title="Attendance Notice",
    section="1. Minimum attendance",
)
LIBRARY = passage(
    "2. Borrowing books\nStudents may borrow up to 4 books at a time, for 14 days.\n"
    "Non-teaching staff may borrow up to 3 books at a time, for 14 days.",
    title="Library Rules",
    section="2. Borrowing books",
)
DATE_SHEET = passage(
    "EXAM DATE SHEET\nWednesday, 2 December 2026    Business Law\nFriday, 4 December 2026    Human Resource Management",
    title="Exam Date Sheet",
    section="EXAM DATE SHEET",
    page=3,
)


DIRECTORY = passage(
    "FACULTY DIRECTORY\n"
    "Dr. Vikram Mehta - Associate Professor\nTeaches: Data Structures\n\n"
    "Ms. Priya Nair - Assistant Professor\nTeaches: Database Management Systems",
    title="Faculty Directory",
    section="FACULTY DIRECTORY",
)


class BuildMessagesTests(SimpleTestCase):
    def test_rules_then_numbered_passages_then_the_question(self):
        messages = grounding.build_messages("When is the Business Law exam?", [ATTENDANCE, DATE_SHEET])
        self.assertEqual(messages[0], {"role": "system", "content": grounding.RULES})
        content = messages[1]["content"]
        self.assertIn("[1] Attendance Notice\n1. Minimum attendance", content)
        self.assertIn("[2] Exam Date Sheet (page 3)\nEXAM DATE SHEET", content)
        self.assertTrue(content.endswith("Question: When is the Business Law exam?"))


class AnswerQuestionTests(SimpleTestCase):
    def test_with_no_permitted_passage_the_model_is_not_asked(self):
        with mock.patch.object(grounding.llm, "generate") as generate:
            result = grounding.answer_question("What is the placement package?", [])
        generate.assert_not_called()
        self.assertEqual((result.text, result.status, result.passages), (NOT_FOUND, "not_found", []))

    def test_the_reply_shape_is_forced(self):
        with mock.patch.object(grounding.llm, "generate", return_value=reply("75%")) as generate:
            grounding.answer_question("What is the minimum attendance?", [ATTENDANCE])
        self.assertEqual(generate.call_args.kwargs["json_schema"], grounding.REPLY_SCHEMA)

    def test_a_part_of_the_question_no_document_covers_makes_it_partial(self):
        with mock.patch.object(grounding.llm, "generate", return_value=reply("Every student must attend at least 75%.")):
            result = grounding.answer_question(
                "What is the minimum attendance, and can I get a sports exemption?",
                [ATTENDANCE],
                uncovered_parts=["can I get a sports exemption"],
            )
        self.assertEqual(result.status, "partial")
        self.assertTrue(result.text.endswith(PARTIAL_NOTE + '"can I get a sports exemption"'))

    def test_uncovered_parts_do_not_turn_a_not_found_into_an_answer(self):
        with mock.patch.object(grounding.llm, "generate", return_value=reply("", status="not_found")):
            result = grounding.answer_question("Fee, and a discount?", [ATTENDANCE], uncovered_parts=["a discount"])
        self.assertEqual(result.text, NOT_FOUND)


class AcceptedAnswerTests(SimpleTestCase):
    def test_a_supported_answer_is_kept_with_its_source(self):
        result = check_reply(
            reply("Students may borrow up to 4 books.", evidence=[(1, "Students may borrow up to 4 books at a time, for 14 days.")]),
            "How many books can students borrow?",
            [LIBRARY],
        )
        self.assertEqual((result.text, result.status, result.passages), ("Students may borrow up to 4 books.", "answered", [LIBRARY]))

    def test_a_quote_given_the_wrong_passage_number_still_counts(self):
        result = check_reply(
            reply("75% of the classes", evidence=[(1, "Every student must attend at least 75% of the classes")]),
            "What is the minimum attendance?",
            [LIBRARY, ATTENDANCE],
        )
        self.assertEqual(result.passages, [ATTENDANCE])

    def test_without_quotes_the_passage_holding_the_answer_is_the_source(self):
        result = check_reply(reply("At least 75% of the classes."), "What is the minimum attendance?", [LIBRARY, ATTENDANCE])
        self.assertEqual(result.passages, [ATTENDANCE])

    def test_the_right_table_row_is_accepted(self):
        result = check_reply(reply("Wednesday, 2 December 2026"), "When is the Business Law exam?", [DATE_SHEET])
        self.assertEqual(result.text, "Wednesday, 2 December 2026")

    def test_a_question_about_a_whole_section_may_use_any_of_its_lines(self):
        # "minimum" and "attendance" are only in the heading, not on the 75% line.
        result = check_reply(reply("75% of the classes."), "What is the minimum attendance?", [ATTENDANCE])
        self.assertEqual(result.status, "answered")

    def test_numbers_from_the_question_itself_are_allowed(self):
        semester = passage("Data Structures is taught in B.Tech Semester 3 by Dr. Vikram Mehta.", title="Faculty Directory")
        result = check_reply(reply("Dr. Vikram Mehta teaches it in Semester 3."), "Who teaches in Semester 3?", [semester])
        self.assertEqual(result.status, "answered")

    def test_a_time_written_in_words_answers_a_when_question(self):
        hostel = passage("Hostel gates close at ten every night.", title="Hostel Rules")
        result = check_reply(reply("Hostel gates close at ten."), "When do hostel gates close?", [hostel])
        self.assertEqual(result.status, "answered")

    def test_the_right_person_from_a_directory_is_accepted(self):
        result = check_reply(reply("Ms. Priya Nair"), "Who teaches Database Management Systems?", [DIRECTORY])
        self.assertEqual(result.text, "Ms. Priya Nair")

    def test_a_leading_yes_or_no_is_removed(self):
        exam = passage("Students debarred for low attendance cannot take the exam of that course.", title="Exam Rules")
        result = check_reply(
            reply("Yes, students debarred for low attendance cannot take the exam."),
            "Can I sit for my exam if my attendance is low?",
            [exam],
        )
        self.assertEqual(result.text, "Students debarred for low attendance cannot take the exam.")

    def test_a_bare_yes_is_replaced_by_the_verified_quote(self):
        # The real reply: "Yes", with the rule quoted correctly.
        medical = passage(
            "4. Medical leave\nMedical leave is counted for attendance only if a medical certificate is submitted.",
            title="Attendance Notice",
            section="4. Medical leave",
        )
        quote = "Medical leave is counted for attendance only if a medical certificate is submitted."
        result = check_reply(reply("Yes", evidence=[(1, quote)]), "Is medical leave counted for attendance?", [medical])
        self.assertEqual((result.text, result.passages), (quote, [medical]))

    def test_a_bare_no_without_a_quote_gets_the_best_matching_sentence(self):
        # The real reply to "can I pay fees in cash?": just "no".
        fees = passage(
            "5. How to pay\nFees are paid online on the student portal. Payment by cash is not accepted.",
            title="Fee Structure",
            section="5. How to pay",
        )
        result = check_reply(reply("no"), "can I pay fees in cash?", [fees])
        self.assertEqual((result.text, result.passages), ("Payment by cash is not accepted.", [fees]))

    def test_a_bare_yes_with_no_real_quote_is_not_an_answer(self):
        with mock.patch.object(grounding.logger, "warning"):
            result = check_reply(reply("Yes", evidence=[(1, "Something not in the passage")]), "Is it allowed?", [LIBRARY])
        self.assertEqual(result.text, NOT_FOUND)

    def test_a_partial_answer_names_what_could_not_be_confirmed(self):
        result = check_reply(
            reply("75% of the classes.", status="partial", missing="exemptions for sports events"),
            "What is the minimum attendance, and are there exemptions?",
            [ATTENDANCE],
        )
        self.assertEqual(result.text, "75% of the classes.\n\n" + PARTIAL_NOTE + "exemptions for sports events")

    def test_a_partial_answer_with_nothing_named_gets_a_general_note(self):
        result = check_reply(reply("75% of the classes.", status="partial", missing="none"), "Minimum attendance?", [ATTENDANCE])
        self.assertTrue(result.text.endswith(PARTIAL_NOTE + grounding.PARTIAL_DEFAULT))


class RejectedAnswerTests(SimpleTestCase):
    def assertNotFound(self, model_reply, question, passages):
        # A rejected answer is logged; the log is silenced to keep test output clean.
        with mock.patch.object(grounding.logger, "warning"):
            result = check_reply(model_reply, question, passages)
        self.assertEqual((result.text, result.passages), (NOT_FOUND, []))

    def test_the_model_says_not_found(self):
        self.assertNotFound(reply("", status="not_found"), "What is the hostel fee?", [ATTENDANCE])

    def test_a_reply_that_is_not_json(self):
        self.assertNotFound("The answer is 75%.", "Minimum attendance?", [ATTENDANCE])

    def test_an_invented_number(self):
        self.assertNotFound(reply("At least 80% of the classes."), "What is the minimum attendance?", [ATTENDANCE])

    def test_an_invented_date(self):
        self.assertNotFound(reply("Monday, 2 December 2026"), "When is the Business Law exam?", [DATE_SHEET])

    def test_a_date_from_the_wrong_table_row(self):
        self.assertNotFound(reply("Friday, 4 December 2026"), "When is the Business Law exam?", [DATE_SHEET])

    def test_an_answer_from_the_models_own_knowledge(self):
        self.assertNotFound(
            reply("The vice chancellor is appointed by the governing board of trustees."),
            "Who is the vice chancellor?",
            [ATTENDANCE],
        )

    def test_an_answer_saying_the_passages_do_not_contain_it(self):
        self.assertNotFound(reply("The salary is not mentioned in the passages."), "What is the salary?", [LIBRARY])

    def test_a_person_from_the_wrong_directory_entry(self):
        # The real mistake: "who teach dbms" was answered with the teacher
        # of Data Structures.
        self.assertNotFound(reply("Dr. Vikram Mehta"), "Who teaches Database Management Systems?", [DIRECTORY])

    def test_an_invented_person(self):
        self.assertNotFound(reply("Dr. Rajesh Kumar"), "Who teaches Database Management Systems?", [DIRECTORY])

    def test_a_fact_from_the_wrong_sentence_of_a_line(self):
        # The real mistake: "I lost my ID card" answered with the RENEWAL deadline.
        card = passage(
            "5. Staff ID card\nThe staff ID card must be renewed every year before 30 June. "
            "A lost card is replaced for Rs 300.",
            title="Non-Teaching Staff Handbook",
            section="5. Staff ID card",
        )
        self.assertNotFound(reply("Replace it before 30 June."), "I lost my ID card, what should I do?", [card])
        result = check_reply(reply("A lost card is replaced for Rs 300."), "I lost my ID card, what should I do?", [card])
        self.assertEqual(result.text, "A lost card is replaced for Rs 300.")

    def test_a_bare_no_is_not_replaced_by_an_unrelated_sentence(self):
        # The real mistake: "can i use kettel in hostel room" answered with
        # the hostel room FEE, because it shared "hostel" and "room".
        fees = passage("Hostel fee (single room, with mess): Rs 1,25,000.", title="Fee Structure", section="2. Other fees")
        self.assertNotFound(reply("No"), "can i use kettel in hostel room", [fees])

    def test_a_fee_question_answered_without_an_amount(self):
        # The real mistake: a student asked about non-teaching staff overtime,
        # and the library line about non-teaching staff was used.
        self.assertNotFound(
            reply("Non-teaching staff may borrow up to 3 books at a time, for 14 days."),
            "What is the overtime rate for non-teaching staff?",
            [LIBRARY],
        )

    def test_a_when_question_answered_without_a_date_or_time(self):
        self.assertNotFound(reply("In the library."), "When do students borrow books?", [LIBRARY])

    def test_a_how_many_question_answered_without_a_number(self):
        self.assertNotFound(reply("Students may borrow books."), "How many books can students borrow?", [LIBRARY])
