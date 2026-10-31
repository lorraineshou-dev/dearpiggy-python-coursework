"""Optional AI tests use injected transports; no real credentials or API calls."""
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from ai_chat import ChatError, ChatService, load_config, request_reply


class AdapterTests(unittest.TestCase):
    def response(self, data):
        return io.BytesIO(json.dumps(data).encode('utf-8'))

    def test_text_only_request_and_response(self):
        sent = []

        def opener(request, timeout):
            sent.append((request, timeout))
            return self.response({'status': 'completed', 'output': [
                {'type': 'reasoning', 'summary': []},
                {'type': 'message', 'content': [{'type': 'output_text', 'text': 'I hear you.'}]}]})

        conversation = [{'role': 'user', 'content': 'Today felt tiring.'}]
        self.assertEqual(request_reply('test-credential', 'gpt-6-luna', conversation, 'en', opener), 'I hear you.')
        request, timeout = sent[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-credential')
        self.assertEqual(payload['input'], conversation)
        self.assertIs(payload['store'], False)
        self.assertIn('English', payload['instructions'])
        self.assertNotIn('test-credential', request.data.decode())
        self.assertEqual(timeout, 45)

    def test_invalid_provider_outputs_are_safe_errors(self):
        for output in [None, [], {'output': None}, {'output': [{'type': 'message', 'content': None}]},
                       {'status': 'incomplete'}, {'output': []},
                       {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'x' * 4001}]}]}]:
            with self.subTest(output_type=type(output).__name__):
                with self.assertRaises(ChatError):
                    request_reply('test', 'configured-model', [], 'zh-CN', lambda *a, **k: self.response(output))
        for raw in [b'not-json', b'x' * 2_000_001]:
            with self.assertRaises(ChatError):
                request_reply('test', 'configured-model', [], 'en', lambda *a, **k: io.BytesIO(raw))

    def test_errors_do_not_expose_provider_body_or_credentials(self):
        for status in (401, 403, 404, 429, 500):
            def opener(*args, **kwargs):
                raise urllib.error.HTTPError('https://example.invalid', status, 'private provider details',
                                             {}, io.BytesIO(b'sensitive provider response'))
            with self.assertRaises(ChatError) as caught:
                request_reply('test-secret', 'model', [], 'en', opener)
            self.assertNotIn('sensitive', str(caught.exception))
            self.assertNotIn('private provider', str(caught.exception))
            self.assertNotIn('test-secret', str(caught.exception))
        with self.assertRaisesRegex(ChatError, 'connection'):
            request_reply('test', 'model', [], 'en', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))

    def test_config_is_data_and_environment_takes_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / '.env.local').write_text('OPENAI_API_KEY="test-file-value"\nOPENAI_MODEL=local-model\n'
                                            'OTHER=$(never-executed)\n', encoding='utf-8')
            self.assertEqual(load_config(path, {}), ('test-file-value', 'local-model'))
            self.assertEqual(load_config(path, {'OPENAI_API_KEY': 'test-env-value', 'OPENAI_MODEL': 'other-model'}),
                             ('test-env-value', 'other-model'))
            self.assertEqual(load_config(path, {'OPENAI_API_KEY': 'your-own-key'})[0], '')
            self.assertEqual(load_config(path, {'OPENAI_MODEL': '../invalid'})[1], 'gpt-6-luna')


class ConversationTests(unittest.TestCase):
    def test_unconfigured_chat_never_contacts_api(self):
        def forbidden(*args):
            self.fail('An unconfigured service must not send requests')
        service = ChatService(requester=forbidden)
        self.assertFalse(service.configured)
        with self.assertRaisesRegex(ChatError, 'not configured'):
            service.send('session', 'Hello', 'en')
        self.assertEqual(service.history('session'), [])

    def test_input_limits_before_request(self):
        service = ChatService('test', requester=lambda *args: self.fail('Invalid input sent'))
        for text in ('', '  ', 'x' * 1001):
            with self.assertRaises(ChatError):
                service.send('session', text, 'en')

    def test_histories_are_isolated_and_bounded(self):
        captured = []
        def reply(key, model, messages, language):
            captured.append(messages)
            return 'A warm reply.'
        service = ChatService('test', requester=reply)
        with patch('ai_chat.time.monotonic', side_effect=[i * 61 for i in range(12)]):
            for number in range(12):
                service.send('first', f'Turn {number}', 'en')
        history = service.history('first')
        self.assertEqual(len(history), 16)
        self.assertEqual(history[0]['content'], 'Turn 4')
        self.assertEqual(service.history('other'), [])
        history[0]['content'] = 'changed outside service'
        self.assertEqual(service.history('first')[0]['content'], 'Turn 4')
        self.assertLessEqual(max(len(messages) for messages in captured), 17)
        service.clear('first')
        self.assertEqual(service.history('first'), [])

    def test_failed_request_preserves_prior_conversation(self):
        service = ChatService('test', requester=lambda *args: 'Hello')
        service.send('session', 'Hi', 'en')
        before = service.history('session')
        service.requester = lambda *args: (_ for _ in ()).throw(ChatError('Try again'))
        with self.assertRaises(ChatError):
            service.send('session', 'Another message', 'en')
        self.assertEqual(service.history('session'), before)
        service.requester = lambda *args: 'Works again'
        service.send('session', 'Retry', 'en')
        self.assertEqual(service.history('session')[-1]['content'], 'Works again')

    def test_clear_during_request_does_not_restore_history(self):
        started, release = threading.Event(), threading.Event()
        def reply(*args):
            started.set()
            release.wait(3)
            return 'Late reply'
        service = ChatService('test', requester=reply)
        worker = threading.Thread(target=service.send, args=('session', 'Hi', 'en'))
        worker.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ChatError, 'short moment'):
                service.send('session', 'Duplicate', 'en')
            service.clear('session')
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(service.history('session'), [])

    def test_shared_rate_limit(self):
        service = ChatService('test', requester=lambda *args: 'Hello')
        with patch('ai_chat.time.monotonic', return_value=100):
            for n in range(8):
                service.send(str(n), 'Hi', 'en')
            with self.assertRaisesRegex(ChatError, 'short moment'):
                service.send('ninth', 'Hi', 'en')
        with patch('ai_chat.time.monotonic', return_value=161):
            self.assertEqual(service.send('ninth', 'Hi', 'en'), 'Hello')


if __name__ == '__main__':
    unittest.main()
