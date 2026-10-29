from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

# How chat history is organised:
#
#   User  1 ── many  Conversation  1 ── many  Message
#
# A conversation belongs to exactly one user, and a message to exactly
# one conversation. Every message has its own timestamp; the 7-day
# retention rule is applied to each message by that timestamp.


# A conversation's title is its first question, cut to this length.
TITLE_LENGTH = 60


def retention_cutoff():
    """The oldest moment a message may come from and still be kept.
    Messages created before this are expired (CHAT_RETENTION_DAYS)."""
    return timezone.now() - timedelta(days=settings.CHAT_RETENTION_DAYS)


def make_title(question):
    """A question, shortened at a word, as a conversation's title."""
    if len(question) <= TITLE_LENGTH:
        return question
    return question[:TITLE_LENGTH].rsplit(" ", 1)[0] + " ..."


class ConversationQuerySet(models.QuerySet):
    def of(self, user):
        """This user's conversations that still hold at least one message
        inside the retention period.

        Every chat view starts from this, so a user can only ever reach
        their own conversations. Asking for anyone else's gives
        "404 Not Found", as if it did not exist.
        """
        return self.filter(user=user, messages__created_at__gte=retention_cutoff()).distinct()


class Conversation(models.Model):
    """One chat: a series of questions and answers by one user."""

    # CASCADE: if the account is deleted, its private history goes with it.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    # The first question, shortened, so the user can recognise the chat.
    title = models.CharField(max_length=100)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    # The time of the newest message. Used to list the newest chats first.
    updated_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    objects = ConversationQuerySet.as_manager()

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"{self.user}: {self.title}"

    def recent_messages(self):
        """The messages that are still inside the retention period, oldest first."""
        return self.messages.filter(created_at__gte=retention_cutoff())


class Message(models.Model):
    """One message in a conversation: the user's question or the answer."""

    class Sender(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Agent Narada"

    # CASCADE: when a conversation is deleted, its messages go with it,
    # so no message is ever left without a conversation.
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    sender = models.CharField(max_length=10, choices=Sender.choices)
    text = models.TextField()
    # For an answer: the documents it came from, for example
    # [{"document_id": 3, "title": "Attendance Policy", "page": 2}].
    sources = models.JSONField(default=list, blank=True)
    # When the message was written. Stored in UTC (USE_TZ = True) and shown
    # in India time. Indexed, because the 7-day cleanup searches by it.
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        # Oldest first, the order a conversation is read in. The id settles
        # the order of two messages saved in the same instant.
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.get_sender_display()}: {self.text[:50]}"


def delete_expired_chats():
    """Permanently delete every message older than the retention period,
    then every conversation left with no messages.

    Returns (messages deleted, conversations deleted).

    Safe to run any number of times: a second run finds nothing old and
    deletes nothing. It looks only at each message's own timestamp, so
    newer messages, in any user's conversations, are never touched.
    """
    cutoff = retention_cutoff()

    # atomic(): all of it happens, or none of it does.
    with transaction.atomic():
        expired = Message.objects.filter(created_at__lt=cutoff)
        # The conversations that are about to lose messages.
        affected = set(expired.values_list("conversation_id", flat=True))
        _, deleted = expired.delete()
        messages_deleted = deleted.get("chat.Message", 0)

        # A conversation with no messages left is deleted too, so nothing
        # is left behind.
        _, deleted = Conversation.objects.filter(messages__isnull=True).delete()
        conversations_deleted = deleted.get("chat.Conversation", 0)

        # A conversation that still has newer messages may just have lost
        # its first question, which is also its title. The title is chat
        # content too, so it is replaced by the oldest question still kept.
        for conversation in Conversation.objects.filter(pk__in=affected):
            first = (
                conversation.messages.filter(sender=Message.Sender.USER).first()
                or conversation.messages.first()
            )
            conversation.title = make_title(first.text)
            conversation.save(update_fields=["title"])

    return messages_deleted, conversations_deleted
