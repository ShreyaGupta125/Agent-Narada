"""Tests for chat/scope.py: small talk, staying on UPES topics, and
follow-up questions. The model is never really called here."""

import json
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from documents.text import keywords

from . import scope


class SmallTalkTests(SimpleTestCase):
    def test_greetings_thanks_and_polite_questions_get_a_reply(self):
        for message in [
            "Hi", "hello!", "Hey there", "Namaste", "hii", "Hello Narada",
            "Thank you", "thanks a lot!", "Thank you so much",
            "How are you?", "What can you do?", "Who are you?", "help",
            "Bye", "Goodbye!", "ok", "Got it.",
            # with spelling mistakes
            "helo", "hlo", "thnx", "thanku", "how r u", "gud morning",
        ]:
            with self.subTest(message=message):
                self.assertTrue(scope.small_talk_reply(message))

    def test_good_morning_is_answered_in_kind(self):
        self.assertTrue(scope.small_talk_reply("Good morning!").startswith("Good morning! I'm Agent Narada"))
        self.assertTrue(scope.small_talk_reply("good evening").startswith("Good evening!"))

    def test_a_greeting_with_a_question_is_not_small_talk(self):
        for message in ["Hi, what is the late fee?", "Thanks, and when is the exam?", "Hello how many books can I borrow"]:
            with self.subTest(message=message):
                self.assertEqual(scope.small_talk_reply(message), "")

    def test_the_greeting_is_removed_before_searching(self):
        self.assertEqual(scope.without_greeting("Hi, what is the late fee?"), "what is the late fee?")
        self.assertEqual(scope.without_greeting("Good evening, when do the gates close?"), "when do the gates close?")
        self.assertEqual(scope.without_greeting("What is the late fee?"), "What is the late fee?")
        self.assertEqual(scope.without_greeting("Hi"), "Hi")  # nothing left: kept as it was


class OffTopicTests(SimpleTestCase):
    def test_clearly_off_topic_questions(self):
        for message in [
            "Who won yesterday's cricket match?",
            "Recommend a good movie",
            "Write a Python function to sort a list",
            "Tell me a joke",
            "Who will win the election?",
        ]:
            with self.subTest(message=message):
                self.assertTrue(scope.is_clearly_off_topic(message))

    def test_a_university_word_keeps_a_question_on_topic(self):
        for message in [
            "When is the cricket ground on campus open?",
            "Is there a music club for students?",
            "What is the dress code?",  # no off-topic word at all
            "Tell me a joke about the exam",
        ]:
            with self.subTest(message=message):
                self.assertFalse(scope.is_clearly_off_topic(message))


class UniversityQuestionTests(SimpleTestCase):
    def ask(self, message, model_reply=None):
        with mock.patch.object(scope.llm, "generate", return_value=model_reply) as generate:
            result = scope.is_university_question(message)
        return result, generate

    def test_university_words_decide_without_the_model(self):
        result, generate = self.ask("Where is the cafeteria?")
        self.assertTrue(result)
        generate.assert_not_called()

    def test_university_officials_are_university_questions(self):
        for message in ["Who is the vice chancellor?", "Who is the registrar?", "Where is the proctor's office?"]:
            with self.subTest(message=message):
                result, generate = self.ask(message)
                self.assertTrue(result)
                generate.assert_not_called()

    def test_off_topic_words_decide_without_the_model(self):
        result, generate = self.ask("Which film won the award?")
        self.assertFalse(result)
        generate.assert_not_called()

    def test_the_model_decides_only_unclear_questions_with_a_forced_reply(self):
        result, generate = self.ask("What is the capital of France?", json.dumps({"topic": "other"}))
        self.assertFalse(result)
        self.assertEqual(generate.call_args.kwargs["json_schema"], scope.CLASSIFY_SCHEMA)

        result, _ = self.ask("Where can I park my bike?", json.dumps({"topic": "university"}))
        self.assertTrue(result)

    def test_an_unreadable_classification_is_treated_as_a_university_question(self):
        # The user then gets the safe "couldn't find sufficient information" reply.
        result, _ = self.ask("What is the capital of France?", "not json")
        self.assertTrue(result)


class FollowUpTests(SimpleTestCase):
    def test_what_counts_as_a_follow_up(self):
        for message, expected in [
            ("and for teaching staff?", True),
            ("What about Sundays?", True),
            ("what is her email?", True),
            ("When is it due?", True),
            ("What is the library fine?", False),
            ("How many books can students borrow?", False),
        ]:
            with self.subTest(message=message):
                self.assertEqual(scope.is_follow_up(message), expected)

    def complete(self, model_reply):
        with mock.patch.object(scope.llm, "generate", return_value=model_reply) as generate:
            question = scope.complete_question("What is the hostel fee for a single room?", "and for twin sharing?")
        return question, generate

    def test_a_follow_up_is_rewritten_into_a_complete_question(self):
        question, generate = self.complete(json.dumps({"question": "What is the hostel fee for twin sharing?"}))
        self.assertEqual(question, "What is the hostel fee for twin sharing?")
        self.assertEqual(generate.call_args.kwargs["json_schema"], scope.REWRITE_SCHEMA)
        # Only the two questions are sent: no earlier answer, no document.
        sent = generate.call_args.args[0][1]["content"]
        self.assertEqual(
            sent, "Earlier question: What is the hostel fee for a single room?\nLatest message: and for twin sharing?"
        )

    def test_a_bad_rewrite_falls_back_to_both_questions_together(self):
        fallback = "What is the hostel fee for a single room? and for twin sharing?"
        for model_reply in ["not json", json.dumps({"question": ""}), json.dumps({"question": "x" * 400})]:
            with self.subTest(model_reply=model_reply[:20]):
                self.assertEqual(self.complete(model_reply)[0], fallback)

    def test_passages_must_be_about_the_latest_message(self):
        def passage(text):
            return SimpleNamespace(terms=" " + " ".join(keywords(text)) + " ")

        fees = passage("Hostel fee for a single room: Rs 1,25,000. Twin sharing: Rs 95,000.")
        salary = passage("Assistant professor salary: pay level 10.")
        message = "And what about the salary of an assistant professor?"
        self.assertEqual(scope.about_the_latest_message([fees, salary], message), [salary])
        self.assertEqual(scope.about_the_latest_message([fees], "and for twin sharing?"), [fees])
