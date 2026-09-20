from __future__ import annotations

import argparse
import collections
import json
import logging
import mimetypes
import queue
import random
import secrets
import sys
import threading
import webbrowser
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from scripts.delete_comments import (
    load_reusable_archive,
    read_deleted_ids,
    retire_archive,
    write_deleted_ids,
)
from scripts.fetch_comments import DATA_DIRECTORY, PROJECT_DIRECTORY, fetch_archive
from tiktok import (
    SESSION_COOKIE_NAME,
    BlockedError,
    Comment,
    CookieFileError,
    DetectionConfig,
    HttpSession,
    LogConfig,
    SessionUser,
    TikTokClient,
    TikTokError,
    TransportError,
    VideoUrlError,
    bind,
    configure_logging,
    connect_login,
    create_session,
    detect_spam,
    format_cookie_header,
    get_archive_path,
    get_logger,
    parse_cookies,
    read_archive,
)
from tiktok.detection import iter_all_comments
from tiktok.logger import ROOT_LOGGER_NAME, ContextFilter

__all__ = [
    'Application',
    'EventBroker',
    'Phase',
    'main',
]

WEB_DIRECTORY = PROJECT_DIRECTORY / 'web'
COOKIE_PATH = PROJECT_DIRECTORY / 'cookies.txt'
LOG_PATH = PROJECT_DIRECTORY / 'logs' / 'bob.jsonl'
SETTINGS_PATH = PROJECT_DIRECTORY / 'settings.json'
DONE_STAMP_LENGTH = 17
DEFAULT_PORT = 8787
LOCAL_HOST = '127.0.0.1'
TOKEN_PLACEHOLDER = '__APP_TOKEN__'
TOKEN_HEADER = 'X-App-Token'
KEEPALIVE_SECONDS = 15.0
MAXIMUM_BODY_BYTES = 2_000_000
LOG_REPLAY_COUNT = 300

logger = get_logger('app')

class Phase(str, Enum):
    IDLE = 'idle'
    SCANNING = 'scanning'
    REVIEW = 'review'
    DELETING = 'deleting'
    DONE = 'done'

class RequestError(Exception):
    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.message = message
        self.status = status
        super().__init__(message)

class JobCancelledError(Exception):
    ...

@dataclass(frozen = True)
class Settings:
    minimum_duplicate_parents: int = 2
    maximum_distinct_parents: int = 3
    minimum_delete_delay_seconds: float = 3.0
    maximum_delete_delay_seconds: float = 8.0

SETTING_LIMITS: Mapping[str, tuple[float, float]] = {
    'minimum_duplicate_parents': (2, 10),
    'maximum_distinct_parents': (1, 20),
    'minimum_delete_delay_seconds': (1, 60),
    'maximum_delete_delay_seconds': (1, 60),
}

@dataclass
class AppState:
    phase: Phase = Phase.IDLE
    session_user: SessionUser | None = None
    is_session_checked: bool = False
    url: str = ''
    archive_path: Path | None = None
    comments: tuple[Comment, ...] = ()
    flagged: dict[str, tuple[str, ...]] = field(default_factory = dict)
    deleted_ids: set[str] = field(default_factory = set)
    message: str = ''

class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[queue.Queue[tuple[str, Mapping[str, object]]]] = set()
        self._recent_logs: collections.deque[Mapping[str, object]] = collections.deque(maxlen = LOG_REPLAY_COUNT)
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[tuple[str, Mapping[str, object]]]:
        subscriber: queue.Queue[tuple[str, Mapping[str, object]]] = queue.Queue()

        with self._lock:
            for payload in self._recent_logs:
                subscriber.put(('log', payload))

            self._subscribers.add(subscriber)

        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[tuple[str, Mapping[str, object]]]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: str, payload: Mapping[str, object]) -> None:
        with self._lock:
            if event == 'log':
                self._recent_logs.append(payload)

            subscribers = tuple(self._subscribers)

        for subscriber in subscribers:
            subscriber.put((event, payload))

class BrokerLogHandler(logging.Handler):
    def __init__(self, broker: EventBroker) -> None:
        super().__init__(level = logging.INFO)
        self._broker = broker
        self.addFilter(ContextFilter())

    def emit(self, record: logging.LogRecord) -> None:
        fields: Mapping[str, object] = getattr(record, 'fields', {})
        self._broker.publish('log', {
            'time': datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
            'level': record.levelname,
            'name': record.name.removeprefix(f'{ROOT_LOGGER_NAME}.'),
            'message': record.getMessage(),
            'fields': {key: str(value) for key, value in fields.items()},
        })

def parse_settings(raw_settings: Mapping[str, object]) -> Settings:
    values: dict[str, Any] = {}

    for setting in fields(Settings):
        lowest, highest = SETTING_LIMITS[setting.name]

        try:
            value = float(cast(Any, raw_settings[setting.name]))
        except (KeyError, TypeError, ValueError) as E:
            raise RequestError(f'{setting.name.replace("_", " ")} must be a number.') from E

        if not lowest <= value <= highest:
            raise RequestError(f'{setting.name.replace("_", " ")} must be between {lowest:g} and {highest:g}.')

        values[setting.name] = int(value) if setting.type == 'int' else value

    settings = Settings(**values)

    if settings.minimum_delete_delay_seconds > settings.maximum_delete_delay_seconds:
        raise RequestError('The shortest pause cannot be longer than the longest pause.')

    return settings

def read_settings(path: Path) -> Settings:
    try:
        return parse_settings(json.loads(path.read_text(encoding = 'utf-8')))
    except (OSError, ValueError, RequestError):
        return Settings()

def read_history(data_directory: Path) -> list[dict[str, object]]:
    runs: list[dict[str, object]] = []

    for progress_path in sorted((data_directory / 'done').glob('*.progress.json'), reverse = True):
        archive_path = progress_path.with_name(progress_path.name.removesuffix('.progress.json') + '.json')

        try:
            archive = read_archive(archive_path)
        except TikTokError:
            continue

        comments_by_id = {comment.comment_id: comment for comment in iter_all_comments(archive.comments)}
        deleted_ids = read_deleted_ids(archive_path)
        runs.append({
            'finished_at': progress_path.name[:DONE_STAMP_LENGTH - 1],
            'handle': archive.handle,
            'video_id': archive.video_id,
            'url': archive.url,
            'scanned': archive.comment_count + archive.replies_fetched,
            'deleted': [
                {'comment_id': comment_id, 'handle': comments_by_id[comment_id].handle, 'text': comments_by_id[comment_id].text}
                for comment_id in sorted(deleted_ids)
                if comment_id in comments_by_id
            ],
        })

    return runs

def describe_error(error: Exception) -> str:
    if isinstance(error, BlockedError):
        return 'TikTok blocked the request, usually with a captcha. Wait a while, then try again.'

    if isinstance(error, VideoUrlError):
        return 'That link does not point to a TikTok post.'

    if isinstance(error, TransportError):
        return 'Could not reach TikTok. Check your internet connection.'

    if isinstance(error, CookieFileError):
        return 'The saved login could not be read. Connect your login again.'

    return str(error)

class Application:
    def __init__(
        self,
        broker: EventBroker,
        cookie_path: Path = COOKIE_PATH,
        data_directory: Path = DATA_DIRECTORY,
        session_factory: Callable[..., Any] = create_session,
        settings_path: Path = SETTINGS_PATH,
    ) -> None:
        self._broker = broker
        self._cookie_path = cookie_path
        self._data_directory = data_directory
        self._session_factory = session_factory
        self._settings_path = settings_path
        self._settings = read_settings(settings_path)
        self._state = AppState()
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._payload_sequence = 0
        self._instance_id = secrets.token_hex(4)

    @property
    def state(self) -> AppState:
        return self._state

    def get_state_payload(self) -> dict[str, object]:
        self._ensure_session_checked()

        with self._lock:
            state = self._state
            self._payload_sequence += 1

            return {
                'instance': self._instance_id,
                'sequence': self._payload_sequence,
                'phase': state.phase.value,
                'session': asdict(state.session_user) if state.session_user else None,
                'url': state.url,
                'comments': [asdict(comment) for comment in state.comments],
                'flagged': {comment_id: list(reasons) for comment_id, reasons in state.flagged.items()},
                'deleted_ids': sorted(state.deleted_ids),
                'message': state.message,
                'settings': asdict(self._settings),
            }

    def get_history_payload(self) -> dict[str, object]:
        return {'runs': read_history(self._data_directory)}

    def update_settings(self, raw_settings: Mapping[str, object]) -> None:
        self._require_idle()
        settings = parse_settings(raw_settings)

        try:
            self._settings_path.write_text(json.dumps(asdict(settings), indent = 2), encoding = 'utf-8')
        except OSError as E:
            raise RequestError('The settings could not be saved to this folder.', HTTPStatus.INTERNAL_SERVER_ERROR) from E

        with self._lock:
            self._settings = settings

            if self._state.phase is Phase.REVIEW and self._state.session_user is not None:
                self._state.flagged = self._detect(self._state.comments, self._state.session_user, self._state.deleted_ids)

        logger.info('settings saved', duplicate_at = settings.minimum_duplicate_parents, reply_limit = settings.maximum_distinct_parents)

    def _detect(self, comments: Sequence[Comment], session_user: SessionUser, deleted_ids: set[str]) -> dict[str, tuple[str, ...]]:
        report = detect_spam(comments, DetectionConfig(
            minimum_duplicate_parents = self._settings.minimum_duplicate_parents,
            maximum_distinct_parents = self._settings.maximum_distinct_parents,
            excluded_user_ids = frozenset({session_user.user_id}),
        ))

        return {
            flagged_comment.comment.comment_id: tuple(reason.value for reason in flagged_comment.reasons)
            for flagged_comment in report.flagged
            if flagged_comment.comment.comment_id not in deleted_ids
        }

    def login(self, cookie_text: str) -> SessionUser:
        self._require_idle()

        try:
            cookies = parse_cookies(cookie_text)
        except (ValueError, KeyError, TypeError) as E:
            raise RequestError('That does not look like a cookie export. Use Export, then JSON, in Cookie-Editor.') from E

        if SESSION_COOKIE_NAME not in {cookie.name for cookie in cookies}:
            raise RequestError('This export has no TikTok login in it. Log in on tiktok.com first, then export again.')

        try:
            session_user, working_cookies = connect_login(cookies, self._session_factory)
        except TikTokError as E:
            raise RequestError(describe_error(E), HTTPStatus.BAD_GATEWAY) from E

        if session_user is None:
            raise RequestError('TikTok says this login is no longer valid. Log in on tiktok.com, export again, and stay logged in afterwards.')

        try:
            self._cookie_path.write_text(format_cookie_header(working_cookies), encoding = 'utf-8')
            self._cookie_path.chmod(0o600)
        except OSError as E:
            raise RequestError('The login could not be saved to this folder.', HTTPStatus.INTERNAL_SERVER_ERROR) from E

        with self._lock:
            self._state = AppState(session_user = session_user, is_session_checked = True)

        logger.info('login connected', handle = session_user.handle)

        return session_user

    def logout(self) -> None:
        self._require_idle()

        try:
            self._cookie_path.unlink(missing_ok = True)
        except OSError as E:
            raise RequestError('The saved login could not be removed.', HTTPStatus.INTERNAL_SERVER_ERROR) from E

        with self._lock:
            self._state = AppState(is_session_checked = True)

        logger.info('login removed')

    def start_scan(self, url: str, should_refresh: bool) -> None:
        self._require_idle()

        if not url.strip():
            raise RequestError('Paste the link to your post first.')

        with self._lock:
            if self._state.session_user is None:
                raise RequestError('Connect your TikTok login first.', HTTPStatus.UNAUTHORIZED)

            self._state.phase = Phase.SCANNING
            self._state.url = url.strip()
            self._state.comments = ()
            self._state.flagged = {}
            self._state.deleted_ids = set()
            self._state.message = ''

        self._start_worker(lambda: self._run_scan(url.strip(), should_refresh))

    def start_delete(self, comment_ids: Sequence[str]) -> None:
        with self._lock:
            if self._state.phase is not Phase.REVIEW:
                raise RequestError('Scan a post before deleting.', HTTPStatus.CONFLICT)

            unknown_ids = [comment_id for comment_id in comment_ids if comment_id not in self._state.flagged]

            if unknown_ids or not comment_ids:
                raise RequestError('Only comments flagged by the last scan can be deleted.')

            self._state.phase = Phase.DELETING

        self._start_worker(lambda: self._run_delete(tuple(comment_ids)))

    def stop(self) -> None:
        self._cancel.set()

    def reset(self) -> None:
        self._require_idle()

        with self._lock:
            self._state = AppState(session_user = self._state.session_user, is_session_checked = True)

    def _require_idle(self) -> None:
        with self._lock:
            if self._state.phase in (Phase.SCANNING, Phase.DELETING):
                raise RequestError('Wait for the current run to finish, or stop it.', HTTPStatus.CONFLICT)

    def _start_worker(self, target: Callable[[], None]) -> None:
        self._cancel.clear()
        self._worker = threading.Thread(target = target, daemon = True)
        self._worker.start()

    def _ensure_session_checked(self) -> None:
        with self._lock:
            if self._state.is_session_checked:
                return

            self._state.is_session_checked = True

        if not self._cookie_path.exists():
            return

        try:
            with self._session_factory(self._cookie_path) as session:
                session_user = TikTokClient(cast(HttpSession, session)).get_session_user()
        except TikTokError as E:
            logger.warning('saved login could not be checked', reason = str(E))
            return

        with self._lock:
            self._state.session_user = session_user

        if session_user is None:
            logger.warning('saved login has expired')
        else:
            logger.info('login is valid', handle = session_user.handle)

    def _fail(self, message: str, phase: Phase) -> None:
        with self._lock:
            self._state.phase = phase
            self._state.message = message

        self._broker.publish('failed', {'message': message, 'phase': phase.value})

    def _on_comment(self, comment: Comment) -> None:
        if self._cancel.is_set():
            raise JobCancelledError

        with self._lock:
            self._state.comments = (*self._state.comments, comment)

        self._broker.publish('comment', {'comment': asdict(comment)})

    def _run_scan(self, url: str, should_refresh: bool) -> None:
        with self._lock:
            session_user = self._state.session_user

        if session_user is None:
            self._fail('Connect your TikTok login first.', Phase.IDLE)
            return

        try:
            with self._session_factory() as anonymous_session:
                client = TikTokClient(cast(HttpSession, anonymous_session))
                reference = client.resolve_video(url)

                if reference.handle != session_user.handle:
                    logger.error('not your post', logged_in_as = session_user.handle, post_owner = reference.handle)
                    self._fail(f'That post belongs to @{reference.handle}. You can only clean up posts from @{session_user.handle}.', Phase.IDLE)
                    return

                archive_path = get_archive_path(self._data_directory, reference.handle, reference.video_id)
                archive = None if should_refresh else load_reusable_archive(archive_path)

                if archive is None:
                    retire_archive(archive_path)
                    archive = fetch_archive(client, reference, self._data_directory, on_comment = self._on_comment)
        except JobCancelledError:
            logger.warning('scan stopped')
            self._fail('Scan stopped. Nothing was deleted.', Phase.IDLE)
            return
        except TikTokError as E:
            logger.error('scan failed', reason = str(E))
            self._fail(describe_error(E), Phase.IDLE)
            return

        deleted_ids = read_deleted_ids(archive_path)
        flagged = self._detect(archive.comments, session_user, deleted_ids)
        message = '' if archive.is_complete else 'TikTok stopped the scan early, so some bot accounts may be missing from this list.'

        with self._lock:
            self._state.phase = Phase.REVIEW
            self._state.archive_path = archive_path
            self._state.comments = archive.comments
            self._state.flagged = flagged
            self._state.deleted_ids = deleted_ids
            self._state.message = message

        self._broker.publish('report', self.get_state_payload())

    def _run_delete(self, comment_ids: tuple[str, ...]) -> None:
        with self._lock:
            archive_path = self._state.archive_path
            url = self._state.url
            deleted_ids = set(self._state.deleted_ids)
            comments_by_id = {comment.comment_id: comment for comment in iter_all_comments(self._state.comments)}
            reasons_by_id = dict(self._state.flagged)

        if archive_path is None:
            self._fail('Scan a post before deleting.', Phase.IDLE)
            return

        deleted_count = 0

        try:
            with self._session_factory(self._cookie_path) as session:
                client = TikTokClient(cast(HttpSession, session))

                for comment_id in comment_ids:
                    if self._cancel.is_set():
                        break

                    comment = comments_by_id[comment_id]

                    with bind(author = comment.handle, text = comment.text, reasons = list(reasons_by_id[comment_id])):
                        client.delete_comment(comment_id, referer = url)

                    deleted_count += 1
                    deleted_ids.add(comment_id)
                    write_deleted_ids(archive_path, deleted_ids)

                    with self._lock:
                        self._state.deleted_ids.add(comment_id)
                        self._state.flagged.pop(comment_id, None)

                    self._broker.publish('deleted', {'comment_id': comment_id, 'done': deleted_count, 'total': len(comment_ids)})

                    if deleted_count < len(comment_ids):
                        self._cancel.wait(random.uniform(self._settings.minimum_delete_delay_seconds, self._settings.maximum_delete_delay_seconds))
        except TikTokError as E:
            logger.error('stopping after failure', reason = str(E))
            self._fail(f'Stopped after {deleted_count} of {len(comment_ids)}. {describe_error(E)}', Phase.REVIEW)
            return

        was_stopped = deleted_count < len(comment_ids)
        logger.info('delete run finished', deleted = deleted_count, requested = len(comment_ids))

        if not was_stopped:
            retire_archive(archive_path)

        with self._lock:
            self._state.phase = Phase.REVIEW if was_stopped else Phase.DONE
            self._state.message = f'Stopped after {deleted_count} of {len(comment_ids)}.' if was_stopped else ''

        self._broker.publish('finished', {'deleted': deleted_count, 'total': len(comment_ids), 'stopped': was_stopped})

def iter_events(
    subscriber: queue.Queue[tuple[str, Mapping[str, object]]],
    keepalive_seconds: float = KEEPALIVE_SECONDS,
) -> Iterator[bytes]:
    while True:
        try:
            event, payload = subscriber.get(timeout = keepalive_seconds)
        except queue.Empty:
            yield b': keepalive\n\n'
            continue

        yield f'event: {event}\ndata: {json.dumps(payload, ensure_ascii = False)}\n\n'.encode()

def build_handler(application: Application, broker: EventBroker, token: str) -> type[BaseHTTPRequestHandler]:
    class RequestHandler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._dispatch('GET')

        def do_POST(self) -> None:
            self._dispatch('POST')

        def _dispatch(self, method: str) -> None:
            path = urlsplit(self.path).path

            try:
                self._require_local_host()

                if not path.startswith('/api/'):
                    self._serve_static(path)
                    return

                self._require_token()

                if (method, path) == ('GET', '/api/events'):
                    self._serve_events()
                    return

                self._send_json(self._call_api(method, path))
            except RequestError as E:
                self._send_json({'error': E.message}, E.status)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _call_api(self, method: str, path: str) -> Mapping[str, object]:
            if (method, path) == ('GET', '/api/state'):
                return application.get_state_payload()

            if (method, path) == ('GET', '/api/history'):
                return application.get_history_payload()

            if method != 'POST':
                raise RequestError('Not found.', HTTPStatus.NOT_FOUND)

            body = self._read_json()

            if path == '/api/login':
                application.login(str(body.get('cookies', '')))
            elif path == '/api/logout':
                application.logout()
            elif path == '/api/scan':
                application.start_scan(str(body.get('url', '')), bool(body.get('refresh', False)))
            elif path == '/api/delete':
                application.start_delete([str(comment_id) for comment_id in body.get('comment_ids', [])])
            elif path == '/api/stop':
                application.stop()
            elif path == '/api/reset':
                application.reset()
            elif path == '/api/settings':
                application.update_settings(body)
            else:
                raise RequestError('Not found.', HTTPStatus.NOT_FOUND)

            return application.get_state_payload()

        def _require_local_host(self) -> None:
            host = (self.headers.get('Host') or '').rsplit(':', 1)[0]

            if host not in (LOCAL_HOST, 'localhost'):
                raise RequestError('This app only answers on this computer.', HTTPStatus.FORBIDDEN)

        def _require_token(self) -> None:
            query_token = parse_qs(urlsplit(self.path).query).get('token', [''])[0]
            provided_token = self.headers.get(TOKEN_HEADER) or query_token

            if not secrets.compare_digest(provided_token, token):
                raise RequestError('Reload the page to continue.', HTTPStatus.FORBIDDEN)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get('Content-Length') or 0)

            if length > MAXIMUM_BODY_BYTES:
                raise RequestError('That is too large to be a cookie export.', HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

            if length == 0:
                return {}

            try:
                body = json.loads(self.rfile.read(length))
            except ValueError as E:
                raise RequestError('The request could not be read.') from E

            if not isinstance(body, dict):
                raise RequestError('The request could not be read.')

            return cast(dict[str, Any], body)

        def _send_json(self, payload: Mapping[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send_bytes(json.dumps(payload, ensure_ascii = False).encode(), 'application/json; charset=utf-8', status)

        def _send_bytes(self, content: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(content)

        def _serve_static(self, path: str) -> None:
            relative_path = 'index.html' if path in ('', '/') else path.lstrip('/')
            file_path = (WEB_DIRECTORY / relative_path).resolve()

            if not file_path.is_relative_to(WEB_DIRECTORY.resolve()) or not file_path.is_file():
                raise RequestError('Not found.', HTTPStatus.NOT_FOUND)

            content = file_path.read_bytes()

            if file_path.name == 'index.html':
                content = content.replace(TOKEN_PLACEHOLDER.encode(), token.encode())

            content_type = mimetypes.guess_type(file_path.name)[0] or 'application/octet-stream'

            if content_type.startswith('text/') or content_type.endswith('javascript'):
                content_type = f'{content_type}; charset=utf-8'

            self._send_bytes(content, content_type)

        def _serve_events(self) -> None:
            subscriber = broker.subscribe()
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'keep-alive')
            self.end_headers()

            try:
                for chunk in iter_events(subscriber):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                broker.unsubscribe(subscriber)

    return RequestHandler

def create_server(application: Application, broker: EventBroker, token: str, port: int) -> ThreadingHTTPServer:
    handler = build_handler(application, broker, token)

    try:
        server = ThreadingHTTPServer((LOCAL_HOST, port), handler)
    except OSError:
        server = ThreadingHTTPServer((LOCAL_HOST, 0), handler)

    server.daemon_threads = True

    return server

def parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = 'Bob: clean bot replies out of your TikTok comments, in your browser')
    parser.add_argument('--port', type = int, default = DEFAULT_PORT)
    parser.add_argument('--no-browser', action = 'store_true', help = 'do not open the browser automatically')

    return parser.parse_args(arguments)

def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    configure_logging(LogConfig(file_path = LOG_PATH))
    broker = EventBroker()
    logging.getLogger(ROOT_LOGGER_NAME).addHandler(BrokerLogHandler(broker))
    application = Application(broker)
    server = create_server(application, broker, secrets.token_urlsafe(32), options.port)
    address = f'http://{LOCAL_HOST}:{server.server_address[1]}/'
    logger.info('bob is running', address = address)
    logger.info('press ctrl+c here to quit')

    if not options.no_browser:
        threading.Timer(0.4, webbrowser.open, args = (address,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('shutting down')
    finally:
        application.stop()
        server.server_close()

    return 0

if __name__ == '__main__':
    sys.exit(main())
