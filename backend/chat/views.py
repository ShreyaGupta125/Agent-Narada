import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import CanChat, CanDeleteOwnChatHistory, CanViewOwnChatHistory
from documents.models import Document, Passage
from documents.retrieval import search, uncovered_parts
from documents.spelling import correct_spelling, vocabulary_of

from . import grounding, llm, scope
from .models import Conversation, Message, make_title

# Errors are written to the terminal where the server runs, so a problem
# with the language model can be found and fixed.
logger = logging.getLogger(__name__)

# A question longer than this is refused, so nobody can send the backend
# (and the language model) an enormous block of text.
MAX_QUESTION_LENGTH = 1000

# How many passages are given to the language model for one question.
# A small model answers best from a few short, relevant passages.
PASSAGES_PER_QUESTION = 4

MODEL_NOT_RUNNING = (
    "Agent Narada's language model is not running right now. "
    "Please try again in a moment."
)

CONVERSATION_NOT_FOUND = (
    "This conversation does not exist or has expired. Please start a new chat."
)


def source_of(passage):
    """Where a passage came from, for the list of sources under an answer."""
    return {
        "document_id": passage.document_id,
        "title": passage.document.title,
        "section": passage.section,
        "page": passage.page,
    }


def vocabulary_for(user):
    """The words spelling mistakes are corrected towards: those of the
    documents this user may read, never another role's documents, so a
    correction cannot hint at what they contain. (The scope word lists,
    scope.WORD_LISTS, are tried after them.)"""
    texts = Passage.objects.filter(document__in=Document.objects.visible_to(user)).values_list("text", flat=True)
    return vocabulary_of(texts)


def earlier_question(conversation):
    """The user's previous question in this conversation (only from the
    last 7 days), or "" if there is none."""
    if conversation is None:
        return ""
    last = conversation.recent_messages().filter(sender=Message.Sender.USER).last()
    return last.text if last else ""


def build_answer(user, question, conversation=None):
    """Produce the reply to a message: (answer, sources).

    1. SMALL TALK  "Hi", "Thank you" ... get a friendly reply (scope.py).
    2. OFF-TOPIC   a clearly unrelated question gets the polite scope reply.
    3. FOLLOW-UP   "and for teaching staff?" is first rewritten into a
                   complete question, using the user's previous question
                   in the same conversation (scope.complete_question).
                   Only the previous QUESTION is used, never an earlier
                   answer, and the search below uses the user's CURRENT
                   permissions, so a follow-up can never reach a document
                   the user may not read now. Passages must also contain
                   the follow-up's own words (scope.about_the_latest_message).
    4. RETRIEVE    the passages that strongly match, among the documents
                   THIS USER's role may read (documents/retrieval.py).
    5. GROUND      found: the model answers, and Django checks the answer
                   against the passages (chat/grounding.py).
                   Not found: a university question gets the "couldn't
                   find sufficient information" reply; anything else gets
                   the polite scope reply.
    6. SOURCES     only the passages that supported the answer.

    Raises llm.LLMUnavailable if the model cannot be reached.
    """
    reply = scope.small_talk_reply(question)
    if reply:
        return reply, []
    message = scope.without_greeting(question)  # "Hi, what is ...?" -> "what is ...?"

    # Spelling mistakes are corrected with the words of the documents THIS
    # user may read ("attendence" -> "attendance"), and short forms written
    # out ("dbms" -> "database management systems"). The corrected question
    # is used from here on; the user's own words are what is saved.
    message = correct_spelling(message, vocabulary_for(user), scope.WORD_LISTS)

    earlier = earlier_question(conversation) if scope.is_follow_up(message) else ""
    if scope.is_clearly_off_topic(message) and not earlier:
        return scope.OFF_TOPIC, []

    # A follow-up is first turned into a complete question.
    asked = scope.complete_question(earlier, message) if earlier else message

    passages = search(user, asked, limit=PASSAGES_PER_QUESTION)
    if earlier:
        passages = scope.about_the_latest_message(passages, message)
    if not passages:
        if scope.is_university_question(asked):
            return grounding.NOT_FOUND, []
        return scope.OFF_TOPIC, []

    uncovered = uncovered_parts(user, asked)
    result = grounding.answer_question(asked, passages, uncovered, focus=message if earlier else "")

    sources = []
    for passage in result.passages:
        source = source_of(passage)
        if source not in sources:  # name each document section and page once
            sources.append(source)
    return result.text, sources


def save_exchange(user, conversation, question, answer, sources):
    """Store one question and its answer. Starts a new conversation when
    none is given. Returns the conversation.

    transaction.atomic(): everything is saved, or nothing is. A question
    is never stored without its answer.
    """
    with transaction.atomic():
        if conversation is None:
            conversation = Conversation.objects.create(user=user, title=make_title(question))
        Message.objects.create(conversation=conversation, sender=Message.Sender.USER, text=question)
        Message.objects.create(
            conversation=conversation,
            sender=Message.Sender.ASSISTANT,
            text=answer,
            sources=sources,
        )
        conversation.updated_at = timezone.now()
        conversation.save(update_fields=["updated_at"])
    return conversation


def conversation_row(conversation):
    """One conversation in the list of a user's chats."""
    return {
        "id": conversation.pk,
        "title": conversation.title,
        "updated_at": conversation.updated_at.isoformat(),
    }


def message_row(message):
    """One message, as the browser shows it."""
    return {
        "id": message.pk,
        "sender": message.sender,
        "text": message.text,
        "sources": message.sources,
        "created_at": message.created_at.isoformat(),
    }


class ChatView(APIView):
    """POST /api/chat/  with {"question": "...", "conversation_id": 12}

    conversation_id is optional: without it a new conversation starts.
    """

    # Checked before post() runs: the user must be logged in and their
    # role must be allowed to chat.
    permission_classes = [CanChat]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        question = str(data.get("question", "")).strip()
        conversation_id = data.get("conversation_id")

        if not question:
            return Response(
                {"detail": "Please type a question."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(question) > MAX_QUESTION_LENGTH:
            return Response(
                {"detail": f"Please keep your question under {MAX_QUESTION_LENGTH} characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Continuing a conversation: it must be one of THIS user's own,
        # still inside the retention period. Checked before the model is
        # asked, so nothing is generated for a request that is refused.
        conversation = None
        if conversation_id is not None:
            # True and False count as numbers in Python, so they are refused by name.
            if not isinstance(conversation_id, int) or isinstance(conversation_id, bool):
                return Response(
                    {"detail": "conversation_id must be a number."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            conversation = Conversation.objects.of(request.user).filter(pk=conversation_id).first()
            if conversation is None:
                return Response(
                    {"detail": CONVERSATION_NOT_FOUND},
                    status=status.HTTP_404_NOT_FOUND,
                )

        try:
            answer, sources = build_answer(request.user, question, conversation)
        except llm.LLMUnavailable as error:
            # The technical reason goes to the server's terminal; the user
            # gets a plain message. 503 means "temporarily unavailable".
            logger.error("Chat could not get an answer: %s", error)
            return Response(
                {"detail": MODEL_NOT_RUNNING},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        conversation = save_exchange(request.user, conversation, question, answer, sources)
        return Response({"answer": answer, "sources": sources, "conversation_id": conversation.pk})


CLEAR_ALL_NEEDS_CONFIRMATION = 'To delete all your conversations, send {"confirm": true}.'


class OwnHistoryPermissions:
    """Reading your history needs "view own chat history"; deleting it
    needs "delete own chat history" (see accounts/permissions.py)."""

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [CanDeleteOwnChatHistory()]
        return [CanViewOwnChatHistory()]


class ConversationListView(OwnHistoryPermissions, APIView):
    """GET    /api/chat/conversations/  -> this user's own chats, newest first.
    DELETE /api/chat/conversations/  with {"confirm": true}
                                     -> delete ALL of this user's chats.
    """

    def get(self, request):
        conversations = Conversation.objects.of(request.user)
        return Response([conversation_row(c) for c in conversations])

    def delete(self, request):
        # A second safety catch after the page's "Are you sure?": the
        # request itself must say it means it, so a stray or buggy request
        # cannot wipe someone's history.
        data = request.data if isinstance(request.data, dict) else {}
        if data.get("confirm") is not True:
            return Response({"detail": CLEAR_ALL_NEEDS_CONFIRMATION}, status=status.HTTP_400_BAD_REQUEST)

        # Only this user's own conversations. CASCADE removes their
        # messages too, so nothing is left behind.
        _, deleted = Conversation.objects.filter(user=request.user).delete()
        return Response({"deleted_conversations": deleted.get("chat.Conversation", 0)})


class ConversationDetailView(OwnHistoryPermissions, APIView):
    """GET    /api/chat/conversations/<id>/  -> one of this user's own chats,
                                              with its messages, oldest first.
    DELETE /api/chat/conversations/<id>/  -> delete it, with its messages.
    Anyone else's conversation gives 404 for both, as if it did not exist.
    """

    def delete(self, request, conversation_id):
        # filter(user=...) makes another user's conversation impossible to
        # find. Its messages go with it (CASCADE).
        conversation = get_object_or_404(Conversation.objects.filter(user=request.user), pk=conversation_id)
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get(self, request, conversation_id):
        conversation = get_object_or_404(Conversation.objects.of(request.user), pk=conversation_id)
        return Response(
            {
                **conversation_row(conversation),
                "messages": [message_row(m) for m in conversation.recent_messages()],
            }
        )
