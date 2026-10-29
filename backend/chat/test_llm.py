"""Tests for chat/llm.py.

These never start the real model. The function that sends the web
request (_send) is replaced with a fake that records what was sent and
returns a prepared reply, so the tests are fast and run anywhere.
"""

import io
import json
from unittest import mock
from urllib.error import URLError

from django.test import SimpleTestCase, override_settings

from . import llm


def model_reply(content):
    """A reply shaped like llama-server's, as the readable stream urlopen gives."""
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    return io.BytesIO(json.dumps(body).encode("utf-8"))


@override_settings(
    LLM_SERVER_URL="http://127.0.0.1:8080",
    LLM_API_KEY="",
    LLM_TEMPERATURE=0.1,
    LLM_MAX_ANSWER_TOKENS=400,
    LLM_TIMEOUT_SECONDS=60,
)
class GenerateTests(SimpleTestCase):
    def send(self, reply=None, error=None, **settings_changes):
        """Call generate() with the fake _send. Returns (answer, request, timeout)."""
        fake = mock.Mock(side_effect=error, return_value=reply)
        with mock.patch.object(llm, "_send", fake), self.settings(**settings_changes):
            result = llm.generate([{"role": "user", "content": "Hi"}])
        request = fake.call_args.args[0]
        return result, request, fake.call_args.kwargs["timeout"]

    def test_returns_the_models_answer_without_extra_spaces(self):
        result, _, _ = self.send(model_reply("  Students must attend 75%.  \n"))
        self.assertEqual(result, "Students must attend 75%.")

    def test_sends_the_conversation_and_settings_to_llama_server(self):
        _, request, timeout = self.send(model_reply("ok"))
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)
        self.assertEqual(body["messages"], [{"role": "user", "content": "Hi"}])
        self.assertEqual(body["temperature"], 0.1)
        self.assertEqual(body["max_tokens"], 400)
        self.assertEqual(timeout, 60)

    def test_sends_the_secret_key_when_one_is_set(self):
        _, request, _ = self.send(model_reply("ok"), LLM_API_KEY="s3cret")
        self.assertEqual(request.get_header("Authorization"), "Bearer s3cret")

    def test_a_json_shape_can_be_forced(self):
        schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
        fake = mock.Mock(return_value=model_reply('{"answer": "ok"}'))
        with mock.patch.object(llm, "_send", fake):
            llm.generate([{"role": "user", "content": "Hi"}], json_schema=schema)
        body = json.loads(fake.call_args.args[0].data)
        self.assertEqual(
            body["response_format"],
            {"type": "json_schema", "json_schema": {"name": "reply", "schema": schema}},
        )

    def test_no_json_shape_is_sent_unless_asked_for(self):
        _, request, _ = self.send(model_reply("ok"))
        self.assertNotIn("response_format", json.loads(request.data))

    def test_sends_no_key_when_none_is_set(self):
        _, request, _ = self.send(model_reply("ok"))
        self.assertIsNone(request.get_header("Authorization"))

    def test_server_not_running(self):
        with self.assertRaises(llm.LLMUnavailable):
            self.send(error=URLError("connection refused"))

    def test_server_too_slow(self):
        with self.assertRaises(llm.LLMUnavailable):
            self.send(error=TimeoutError("timed out"))

    def test_reply_that_is_not_json(self):
        with self.assertRaises(llm.LLMUnavailable):
            self.send(io.BytesIO(b"<html>error</html>"))

    def test_reply_with_an_unexpected_shape(self):
        with self.assertRaises(llm.LLMUnavailable):
            self.send(io.BytesIO(b'{"error": "model not loaded"}'))

    def test_empty_answer(self):
        with self.assertRaises(llm.LLMUnavailable):
            self.send(model_reply("   "))
