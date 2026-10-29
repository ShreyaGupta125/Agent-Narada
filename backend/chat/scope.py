"""Keeping Agent Narada to its job: UPES university information, plus
the ordinary conversation needed to talk to it naturally.

Every message is sorted into one of three kinds:

    SMALL TALK    "Hi", "Thank you", "How are you?"
                  -> a friendly reply written here. No document search,
                     no model: nothing can go wrong or leak.
    OFF-TOPIC     "Who won yesterday's cricket match?"
                  -> the polite OFF_TOPIC reply below.
    UNIVERSITY    everything else -> searched in the documents the user's
                  role may read, and answered with checked evidence.

This is decided in Django code (here and in chat/views.py), not left to
the model's prompt. The model is asked only in one narrow case: when no
document matched and the words alone do not show whether the question
is about the university (is_university_question).
"""

import json
import re

from documents.text import keywords

from . import llm

OFF_TOPIC = (
    "I'm Agent Narada, designed to help with UPES university-related information. "
    "I can assist you with university policies, attendance, examinations, academic "
    "information, and other UPES-related queries."
)

# ---------- Small talk ----------

GREETING_REPLY = (
    "Hello! I'm Agent Narada, the UPES university assistant. Ask me about attendance, "
    "examinations, fees, the library, hostels or other university information."
)

# (pattern for the whole message, reply). A message counts as small talk
# only if it is NOTHING but small talk: "Hi, what is the late fee?" is a
# university question and is answered as one.
SMALL_TALK = [
    # Common misspellings are included: "helo", "thnx", "gud morning".
    (r"(hi+|hy|hie|hello+|helo|hlo|hey+|hey there|namaste|hello there|greetings)( narada| agent narada)?", GREETING_REPLY),
    (r"(?:good|gud|gd) (morning|afternoon|evening)( narada| agent narada)?", None),  # replied with the same greeting
    (
        r"(thank you|thanks|thank u|thanku|thankyou|thanks a lot|thank you so much|many thanks|thx|thnx|thanx|thnks|tnx|ty)( narada| agent narada)?",
        "You're welcome! Is there anything else about the university I can help you with?",
    ),
    (
        r"(how are you|how are you doing|how r u|how are u|hw r u|how's it going|how do you do)",
        "I'm doing well, thank you for asking! How can I help you with university information today?",
    ),
    (
        r"(who are you|what are you|what can you do|what do you do|how can you help( me)?|help)",
        "I'm Agent Narada, the UPES university assistant. I answer questions using the official "
        "university documents available to you, and I show which document each answer comes from. "
        "Try asking about attendance, examinations, fees, the library or hostels.",
    ),
    (
        r"(bye|goodbye|good bye|see you|see you later|good night)",
        "Goodbye! Come back any time you have a question about the university.",
    ),
    (
        r"(ok|okay|alright|all right|cool|great|nice|got it|i see|fine|sure)",
        "Alright! Let me know if you have any other question about the university.",
    ),
]
SMALL_TALK = [(re.compile(rf"^\s*{pattern}\s*[!.?,]*\s*$", re.IGNORECASE), reply) for pattern, reply in SMALL_TALK]


def small_talk_reply(message):
    """The reply to a message that is only small talk, or "" if it is not."""
    for pattern, reply in SMALL_TALK:
        match = pattern.match(message)
        if match:
            if reply is None:  # "Good morning" -> "Good morning! I'm Agent Narada ..."
                return f"Good {match.group(1).lower()}! " + GREETING_REPLY.removeprefix("Hello! ")
            return reply
    return ""


# ---------- University or not ----------

# Words that show a question is about university matters. They are put
# through keywords(), so they match questions the same way the search
# does ("fees" -> "fee", "examinations" -> "exam").
UNIVERSITY_WORD_LIST = (
        "university upes college campus student students faculty professor teacher lecturer "
        "staff employee dean hod head department school programme program course courses "
        "subject semester class lecture tutorial lab attendance exam test quiz assignment "
        "project result results grade marks cgpa sgpa credit syllabus timetable schedule "
        "admission admissions enrolment registration fee fees tuition scholarship hostel mess "
        "warden library book books canteen cafeteria transport bus placement internship "
        "convocation degree certificate id card leave holiday holidays vacation salary "
        "increment hr policy rule rules regulation ragging discipline gym club fest portal "
        "office block room hall notice circular deadline form application apply refund "
        "condonation debarred medical sports wifi "
        # University officials and offices
        "chancellor vice-chancellor vc registrar provost principal director controller "
        "counsellor coordinator proctor cell committee administration"
)
UNIVERSITY_WORDS = set(keywords(UNIVERSITY_WORD_LIST))

# Words that show a question is about something else, when no
# university word is present ("cricket match" alone, but not "cricket
# ground on campus").
OFF_TOPIC_WORD_LIST = (
        # Not here on purpose: "code" ("dress code") and "share" ("share
        # notes"), which are common in university questions too.
        "cricket football ipl match movie movies film films song songs music singer actor "
        "actress celebrity recipe cook cooking weather stock stocks market bitcoin crypto "
        "election elections minister politics political president prime war joke jokes poem "
        "story game games netflix python javascript java coding"
)
OFF_TOPIC_WORDS = set(keywords(OFF_TOPIC_WORD_LIST))

# Both lists as plain words, for spelling correction ("crikcet" -> "cricket").
WORD_LISTS = (UNIVERSITY_WORD_LIST + " " + OFF_TOPIC_WORD_LIST).split()

CLASSIFY_RULES = """You sort messages sent to a university's assistant.
Reply "university" if the message is about university or college matters: studies, courses, exams, attendance, fees, scholarships, staff, faculty, officials (such as the vice chancellor or registrar), departments, campus facilities, hostels, the library, transport, admissions, rules or procedures.
Reply "other" for anything else, for example sports results, films, music, news, politics, general knowledge, coding help or cooking.
The message may have spelling or grammar mistakes, or Hindi words written in English: judge what the user means."""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"enum": ["university", "other"]}},
    "required": ["topic"],
}


def is_clearly_off_topic(message):
    """True if the message has off-topic words and no university word.
    Such a message is refused before any document is searched."""
    words = set(keywords(message))
    return bool(words & OFF_TOPIC_WORDS) and not words & UNIVERSITY_WORDS


def is_university_question(message):
    """Is a message (that no document matched) about the university?

    University words decide it; off-topic words decide it. Only when the
    words cannot tell ("What is the capital of France?") is the model
    asked, with one narrow question whose reply is forced to be
    "university" or "other".
    Raises llm.LLMUnavailable if the model is needed and not running.
    """
    words = set(keywords(message))
    if words & UNIVERSITY_WORDS:
        return True
    if words & OFF_TOPIC_WORDS:
        return False
    reply = llm.generate(
        [{"role": "system", "content": CLASSIFY_RULES}, {"role": "user", "content": message}],
        json_schema=CLASSIFY_SCHEMA,
    )
    try:
        return json.loads(reply).get("topic") != "other"
    except (ValueError, AttributeError):
        # An unreadable reply: treat it as a university question. The user
        # then gets the safe "couldn't find sufficient information" reply.
        return True


LEADING_GREETING = re.compile(
    r"^\s*(hi+|hy|hie|hello+|helo|hlo|hey+|namaste|(?:good|gud|gd) (morning|afternoon|evening))"
    r"( narada| agent narada)?\b[\s,!.:-]*",
    re.IGNORECASE,
)


def without_greeting(message):
    """"Hi, what is the late fee?" -> "what is the late fee?". The
    greeting is not part of the question and must not be searched for."""
    rest = LEADING_GREETING.sub("", message, count=1)
    return rest if rest.strip() else message


# ---------- Follow-up questions ----------

# "and for teaching staff?", "what about the fee?", "when is it due?"
FOLLOW_UP_START = re.compile(r"^\s*(and|also|what about|how about|same|then|so|but|or)\b", re.IGNORECASE)
FOLLOW_UP_WORDS = re.compile(r"\b(it|its|that|this|those|these|they|them|there|same|he|she|him|her)\b", re.IGNORECASE)


def is_follow_up(message):
    """Does the message lean on an earlier question to make sense? It
    does if it starts like a continuation ("and ...", "what about ...")
    or points back with a word like "it", "her" or "they"."""
    return bool(FOLLOW_UP_START.match(message) or FOLLOW_UP_WORDS.search(message))


# The examples are deliberately NOT from the university's documents, so
# they teach the pattern without suggesting any answer.
REWRITE_RULES = """Rewrite the user's latest message as ONE complete question about ONLY what the latest message asks, using the earlier question just to fill in what is missing.
Do not repeat the earlier question's own subject if the latest message replaces it. Do not answer. Do not add facts, names or numbers.
The messages may have spelling or grammar mistakes: write the new question in correct English.

Examples:
Earlier question: What is the fee for the B.Tech course?
Latest message: and for MBA?
Question: What is the fee for the MBA course?

Earlier question: When does the canteen open on weekdays?
Latest message: what about Sundays?
Question: When does the canteen open on Sundays?

Earlier question: Who is the head of the physics department?
Latest message: what is his phone number?
Question: What is the phone number of the head of the physics department?"""

REWRITE_SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}

# A rewritten question longer than this is not trusted.
MAX_REWRITTEN_LENGTH = 300


def complete_question(earlier, message):
    """A follow-up turned into a question that stands on its own:
    ("When is the Data Structures exam?", "and Discrete Mathematics?")
    -> "When is the Data Structures and Discrete Mathematics exams?"

    Only the user's own earlier QUESTION is used (never an earlier
    answer). The result is then searched with the user's CURRENT
    permissions and checked like any other question, so the rewrite can
    never open a document the user may not read.
    Raises llm.LLMUnavailable if the model is not running.
    """
    fallback = f"{earlier} {message}"
    reply = llm.generate(
        [
            {"role": "system", "content": REWRITE_RULES},
            {"role": "user", "content": f"Earlier question: {earlier}\nLatest message: {message}"},
        ],
        json_schema=REWRITE_SCHEMA,
    )
    try:
        question = " ".join(str(json.loads(reply).get("question") or "").split())
    except (ValueError, AttributeError):
        return fallback
    if not question or len(question) > MAX_REWRITTEN_LENGTH:
        return fallback
    return question


def about_the_latest_message(passages, message):
    """Keep only the passages that contain at least half of the latest
    message's own words.

    A safety net for follow-ups: after "What is the hostel fee?", the
    message "And what about the salary of an assistant professor?" is
    about salaries. A fee passage has none of "salary", "assistant",
    "professor", so it is dropped, and can never be used to answer it."""
    own_words = set(keywords(message))
    if not own_words:
        return passages
    return [
        passage
        for passage in passages
        if len(own_words & set(passage.terms.split())) * 2 >= len(own_words)
    ]
