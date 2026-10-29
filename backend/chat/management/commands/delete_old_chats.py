"""python manage.py delete_old_chats

Permanently deletes chat messages older than CHAT_RETENTION_DAYS (7 days),
and conversations left with no messages. Windows Task Scheduler runs it
every hour (see schedule_chat_cleanup.ps1), so nobody has to open the
application or delete anything by hand.

Django finds this command because the file sits in
<app>/management/commands/; the file name is the command's name.
"""

import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from chat.models import delete_expired_chats


class Command(BaseCommand):
    help = (
        "Permanently delete chat messages older than CHAT_RETENTION_DAYS days, "
        "and conversations left empty. Safe to run any number of times."
    )

    def handle(self, *args, **options):
        messages, conversations = delete_expired_chats()

        # Task Scheduler runs this with pythonw.exe, which opens no window
        # and so has nowhere to print. The deletion above has already
        # happened; only the message below is skipped.
        if sys.stdout is None:
            return
        self.stdout.write(
            f"Deleted {messages} message(s) and {conversations} conversation(s) "
            f"older than {settings.CHAT_RETENTION_DAYS} days."
        )
