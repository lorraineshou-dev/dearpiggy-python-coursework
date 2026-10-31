# MAIN ENTRY POINT: run `python3 main.py` (Windows: `py -3 main.py`).
# Then open http://127.0.0.1:4180. Read README.txt for requirements and disclosure.
"""Dear Piggy: Python HTTP controller, local sessions and application startup.

No third-party packages are required. Business rules are in game.py, durable
state in storage.py, and HTML is rendered by views.py. This server is for local
coursework use, not a production internet deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import mimetypes
import re
import secrets
import threading
from html import escape
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from ai_chat import ChatError, ChatService, load_config
from game import apply_action
from storage import Store
from views import render_page

ROOT = Path(__file__).resolve().parent
PAGES = {'/': 'home', '/care': 'care', '/feelings': 'feelings', '/chat': 'chat',
         '/shop': 'shop', '/growth': 'growth', '/settings': 'settings'}
MAX_BODY = 5 * 1024 * 1024
COOKIE_NAME = 'dearpiggy_coursework'


class Application:
    def __init__(self, data_dir, chat_service=None):
        self.store = Store(Path(data_dir) / 'piggy.sqlite3')
        self.chat = chat_service if chat_service is not None else ChatService(*load_config(ROOT))
        self.secret = secrets.token_bytes(32)
        self._flashes = {}
        self._lock = threading.RLock()

    def csrf(self, session):
        return hmac.new(self.secret, session.encode('ascii'), hashlib.sha256).hexdigest()

    def flash(self, session, message=None):
        with self._lock:
            if message is not None:
                self._flashes[session] = message
            else:
                return self._flashes.pop(session, '')


def make_server(port=4180, data_dir=None, chat_service=None):
    """Also used by integration tests with port=0 and a temporary data directory."""
    app = Application(data_dir or ROOT / 'data', chat_service)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'DearPiggy/1.0'

        def log_message(self, *_args):
            # Diary text, chat content, cookies and query strings are not logged.
            pass

        def send_content(self, status, content, mime='text/html; charset=utf-8', headers=None):
            body = content.encode('utf-8') if isinstance(content, str) else content
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'same-origin')
            self.send_header('Content-Security-Policy',
                             "default-src 'self'; img-src 'self' data: blob:; "
                             "style-src 'self'; script-src 'self'; "
                             "media-src 'self' blob:; font-src 'self'; connect-src 'self'; "
                             "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def error(self, status, message):
            self.send_content(status, '<!doctype html><meta charset="utf-8"><title>Dear Piggy</title>'
                              '<h1>Dear Piggy</h1><p>' + escape(message) + '</p><a href="/">Home</a>')

        def valid_origin(self):
            host = self.headers.get('Host', '')
            port = self.server.server_port
            if host not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                return False
            origin = self.headers.get('Origin')
            return (origin is None or origin == 'http://' + host) and self.headers.get('Sec-Fetch-Site') != 'cross-site'

        def session(self, create=False):
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                value = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ''
            except CookieError:
                value = ''
            if re.fullmatch(r'[a-f0-9]{64}', value):
                return value, {}
            if not create:
                return '', {}
            value = secrets.token_hex(32)
            return value, {'Set-Cookie': f'{COOKIE_NAME}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000'}

        def page(self, page, session, query=None, headers=None, chat_error=''):
            state = app.store.get(session)
            if not state['welcomed'] and page == 'home':
                page = 'welcome'
            flash = app.flash(session)
            if isinstance(flash, (tuple, list)):
                flash = flash[1 if state['lang'] == 'en' else 0]
            html = render_page(page, state, app.csrf(session), query=query or {},
                               chat=app.chat.history(session), chat_ready=app.chat.configured,
                               message=flash or '', chat_error=chat_error)
            self.send_content(200, html, headers=headers)

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.valid_origin():
                return self.error(403, 'Only requests from this local application are allowed.')
            try:
                parsed = urlsplit(self.path)
            except ValueError:
                return self.error(400, 'Invalid request path.')
            if parsed.scheme or parsed.netloc:
                return self.error(400, 'Invalid request path.')
            path = unquote(parsed.path)
            if re.search(r'[\x00-\x1f\x7f]', path):
                return self.error(400, 'Invalid request path.')
            if path.startswith('/static/'):
                static = (ROOT / 'static').resolve()
                try:
                    file = (static / path[len('/static/'):]).resolve()
                except (OSError, ValueError, RuntimeError):
                    return self.error(404, 'File not found.')
                allowed = {'.css', '.js', '.png', '.svg', '.jpg', '.jpeg', '.webp', '.m4a', '.woff2', '.ttf'}
                if (static not in file.parents or file.suffix.lower() not in allowed
                        or any(part.startswith('.') for part in Path(path).parts) or not file.is_file()):
                    return self.error(404, 'File not found.')
                mime = {'.js': 'text/javascript', '.m4a': 'audio/mp4', '.woff2': 'font/woff2'}.get(file.suffix)
                return self.send_content(200, file.read_bytes(), mime or mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
            if path == '/breathe':
                path = '/feelings'
            if path not in PAGES:
                return self.error(404, 'Page not found.')
            try:
                query = {k: v[-1] for k, v in parse_qs(parsed.query, max_num_fields=20).items()}
            except ValueError:
                return self.error(400, 'Too many page options.')
            session, headers = self.session(create=True)
            self.page(PAGES[path], session, query, headers)

        def form(self):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked requests are not supported.')
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/x-www-form-urlencoded':
                raise ValueError('Use the application form to submit this action.')
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                raise ValueError('Invalid request size.') from None
            if not 0 < length <= MAX_BODY:
                raise ValueError('The submitted form is too large or empty.')
            self.connection.settimeout(15)
            text = self.rfile.read(length).decode('utf-8')
            values = parse_qs(text, keep_blank_values=True, max_num_fields=40)
            if any(len(value) != 1 for value in values.values()):
                raise ValueError('Duplicate form fields are not accepted.')
            return {key: value[0] for key, value in values.items()}

        def redirect(self, path):
            try:
                parsed = urlsplit(path)
                valid = (not parsed.scheme and not parsed.netloc and parsed.path in PAGES
                         and len(path) <= 2048 and not re.search(r'[\x00-\x1f\x7f]', path))
            except ValueError:
                valid = False
            if not valid:
                path = '/'
            path = quote(path, safe="/?&=%#:+,;~@!$'()*[]")
            self.send_content(303, b'', headers={'Location': path})

        def do_POST(self):
            if not self.valid_origin():
                return self.error(403, 'Only requests from this local application are allowed.')
            if self.path not in ('/action', '/chat', '/chat/clear'):
                return self.error(404, 'Action not found.')
            session, _ = self.session()
            try:
                form = self.form()
            except (ValueError, UnicodeError, OSError) as error:
                return self.error(400, str(error))
            token = form.get('csrf', '')
            if (not session or not re.fullmatch(r'[a-f0-9]{64}', token)
                    or not hmac.compare_digest(token, app.csrf(session))):
                return self.error(403, 'This form has expired. Reload the page and try again.')
            if self.path == '/chat/clear':
                app.chat.clear(session)
                return self.redirect('/chat')
            if self.path == '/chat':
                state = app.store.get(session)
                try:
                    app.chat.send(session, form.get('message', ''), state['lang'])
                except ChatError as error:
                    return self.page('chat', session, query={'draft': form.get('message', '')[:1000]}, chat_error=str(error))
                return self.redirect('/chat')
            try:
                _, message = app.store.mutate(session, lambda state: apply_action(state, form.get('action', ''), form))
                app.flash(session, message)
            except ValueError as error:
                app.flash(session, str(error))
            self.redirect(form.get('next', '/'))

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.application = app
    return server


def main():
    parser = argparse.ArgumentParser(description='Run the local Dear Piggy Python coursework application.')
    parser.add_argument('--port', type=int, default=4180, help='Local port (default: 4180).')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data', help='Folder for the local SQLite database.')
    options = parser.parse_args()
    if not 1 <= options.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        server = make_server(options.port, options.data_dir)
    except OSError:
        parser.exit(1, 'Could not start the local server. Check the data folder and try --port 4181.\n')
    print(f'Dear Piggy: http://127.0.0.1:{options.port}/', flush=True)
    print('Press Ctrl+C to stop. Core features do not require an API key.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nGoodbye. Your local progress has been saved.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
