"""Tests for documents/spelling.py: correcting spelling mistakes with
the words of the documents."""

from django.test import SimpleTestCase

from .spelling import correct_spelling, vocabulary_of

DOCUMENTS = [
    "Every student must attend at least 75% of the classes. The attendance cell is in Block 5.",
    "Students may borrow up to 4 books from the library. The library opens at 8 am.",
    "The hostel gates close at 10:00 pm. The hostel fee and tuition fees are due in January.",
    "Dr. Vikram Mehta teaches Data Structures. Ms. Priya Nair is teaching Database Management Systems.",
    "Scholarship: students who score 90% or more. Gym membership is Rs 1,500.",
]
VOCABULARY = vocabulary_of(DOCUMENTS)


def correct(text, extra_words=()):
    return correct_spelling(text, VOCABULARY, extra_words)


class CorrectionTests(SimpleTestCase):
    def test_common_mistakes_are_corrected(self):
        cases = {
            "wat is attendence criteria for studnts": "wat is attendance criteria for students",
            "how many book i can borow from libray": "how many book i can borrow from library",
            "hostal gate closing time": "hostel gate closing time",
            "scolarship and gym membersip": "scholarship and gym membership",
        }
        for wrong, right in cases.items():
            with self.subTest(wrong=wrong):
                self.assertEqual(correct(wrong), right)

    def test_short_forms_are_written_out(self):
        self.assertEqual(correct("who teaches dbms"), "who teaches database management systems")
        self.assertEqual(correct("btech fees"), "B.Tech fees")

    def test_correct_words_are_never_changed(self):
        # "teach" is not in the documents, but "teaches"/"teaching" are:
        # it is another form of a known word, not a mistake.
        self.assertEqual(correct("who teach data structures"), "who teach data structures")
        for text in ["what is the minimum attendance?", "Can I take a sabbatical?", "When is the exam?"]:
            with self.subTest(text=text):
                self.assertEqual(correct(text), text)

    def test_a_tie_goes_to_the_word_used_most_in_the_documents(self):
        # "fess" is as close to "fees" as to "fest"; only "fees" is in the documents.
        self.assertEqual(correct("late fee for not paying fess", extra_words=["fest"]), "late fee for not paying fees")

    def test_words_outside_the_documents_are_used_only_when_nothing_closer_exists(self):
        self.assertEqual(correct("crikcet score", extra_words=["cricket"]), "cricket score")

    def test_short_words_and_unlike_words_are_left_alone(self):
        self.assertEqual(correct("wat is the capital of france"), "wat is the capital of france")
        self.assertEqual(correct("bus"), "bus")

    def test_the_first_letter_must_match(self):
        # "ostel" is close to "hostel", but typing mistakes rarely change
        # the first letter, so it is not guessed.
        self.assertEqual(correct("ostel rules"), "ostel rules")
