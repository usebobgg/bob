from __future__ import annotations

import json
import math
import os
import random
import re
import shlex
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from tiktok.logger import bind, get_logger
from tiktok.models import (
    ApiPath,
    ArchiveReadError,
    ArchiveWriteError,
    BlockedError,
    Comment,
    CommentArchive,
    Cookie,
    CookieFileError,
    DeleteFailedError,
    FetchConfig,
    HttpResponse,
    HttpSession,
    LoginResult,
    NotLoggedInError,
    PageParseError,
    Profile,
    ProfileUnavailableError,
    QueryValue,
    RawActionResult,
    RawAppContext,
    RawComment,
    RawCommentPage,
    RawEmbedVideo,
    RawExportedCookie,
    RawSessionUser,
    RawUserDetail,
    ReplyThread,
    SessionUser,
    TransportError,
    Video,
    VideoReference,
    VideoUrlError,
)

__all__ = [
    'DATA_CENTRE_COOKIE_NAME',
    'KNOWN_DATA_CENTRES',
    'SESSION_COOKIE_NAME',
    'ScriptId',
    'TikTokClient',
    'build_archive',
    'connect_login',
    'create_session',
    'ensure_cookie_file',
    'extract_script_json',
    'format_cookie_header',
    'get_archive_path',
    'get_script_pattern',
    'get_video_url_pattern',
    'parse_archived_comment',
    'parse_comment',
    'parse_cookie_header',
    'parse_cookies',
    'parse_dropped_path',
    'parse_json_cookies',
    'parse_netscape_cookies',
    'parse_profile',
    'parse_session_user',
    'parse_video_url',
    'parse_videos',
    'read_archive',
    'read_cookie_file',
    'write_archive',
]

ScriptId = Literal['__UNIVERSAL_DATA_FOR_REHYDRATION__', '__FRONTITY_CONNECT_STATE__']

@lru_cache(maxsize = None)
def get_script_pattern(script_id: ScriptId) -> re.Pattern[str]:
    return re.compile(rf'<script id="{script_id}"[^>]*>(.*?)</script>', re.DOTALL)

def extract_script_json(html: str, script_id: ScriptId, url: str) -> dict[str, Any]:
    match = get_script_pattern(script_id).search(html)

    if match is None:
        raise BlockedError(url, f'{script_id} script is missing from the page')

    try:
        return cast(dict[str, Any], json.loads(match.group(1)))
    except json.JSONDecodeError as E:
        raise PageParseError(url, f'{script_id} is not valid JSON') from E

def parse_profile(detail: RawUserDetail, handle: str, url: str) -> Profile:
    status_code = detail.get('statusCode')

    if status_code != 0:
        raise ProfileUnavailableError(handle, status_code)

    try:
        user = detail['userInfo']['user']
        stats = detail['userInfo']['stats']

        return Profile(
            user_id = user['id'],
            secure_user_id = user['secUid'],
            handle = user['uniqueId'],
            nickname = user['nickname'],
            biography = user.get('signature', ''),
            is_verified = user.get('verified', False),
            is_private = user.get('privateAccount', False),
            follower_count = stats['followerCount'],
            following_count = stats['followingCount'],
            like_count = stats['heartCount'],
            video_count = stats['videoCount'],
        )
    except KeyError as E:
        raise PageParseError(url, f'profile field {E} is missing') from E

def parse_videos(raw_videos: Sequence[RawEmbedVideo], handle: str, base_url: str) -> tuple[Video, ...]:
    return tuple(
        Video(
            video_id = raw_video['id'],
            description = raw_video.get('desc', ''),
            play_count = raw_video.get('playCount'),
            url = f'{base_url}/@{handle}/video/{raw_video["id"]}',
        )
        for raw_video in raw_videos
    )

def parse_comment(
    raw_comment: RawComment,
    parent_comment_id: str | None = None,
    replies: tuple[Comment, ...] = (),
    reply_count: int | None = None,
) -> Comment:
    user = raw_comment.get('user') or {}
    resolved_reply_count = raw_comment.get('reply_comment_total', 0) if reply_count is None else reply_count

    return Comment(
        comment_id = raw_comment['cid'],
        parent_comment_id = parent_comment_id,
        video_id = raw_comment.get('aweme_id'),
        text = raw_comment.get('text', ''),
        created_at = raw_comment.get('create_time'),
        like_count = raw_comment.get('digg_count', 0),
        reply_count = resolved_reply_count,
        has_image = bool(raw_comment.get('image_list')),
        user_id = user.get('uid'),
        handle = user.get('unique_id'),
        nickname = user.get('nickname'),
        replies = replies,
    )

@lru_cache(maxsize = None)
def get_video_url_pattern() -> re.Pattern[str]:
    return re.compile(r'tiktok\.com/@(?P<handle>[^/?#]*)/(?:video|photo)/(?P<video_id>\d+)')

def parse_video_url(url: str) -> VideoReference | None:
    match = get_video_url_pattern().search(url)

    if match is None:
        return None

    return VideoReference(
        handle = match.group('handle') or None,
        video_id = match.group('video_id'),
        url = url.split('?', 1)[0],
    )

def parse_cookie_header(text: str) -> tuple[Cookie, ...]:
    header = text.strip().removeprefix('Cookie:').removeprefix('cookie:').strip()
    pairs = (pair.strip().split('=', 1) for pair in header.split(';') if '=' in pair)

    return tuple(Cookie(name = name.strip(), value = value.strip()) for name, value in pairs)

def parse_netscape_cookies(text: str) -> tuple[Cookie, ...]:
    cookies: list[Cookie] = []

    for line in text.splitlines():
        fields = line.removeprefix('#HttpOnly_').split('\t')

        if line.startswith('# ') or len(fields) != NETSCAPE_FIELD_COUNT:
            continue

        cookies.append(Cookie(name = fields[5], value = fields[6], domain = fields[0]))

    return tuple(cookies)

def parse_json_cookies(payload: object) -> tuple[Cookie, ...]:
    if isinstance(payload, dict) and isinstance(payload.get('cookies'), list):
        payload = payload['cookies']

    if isinstance(payload, dict):
        return tuple(Cookie(name = str(name), value = str(value)) for name, value in payload.items())

    if not isinstance(payload, list):
        raise ValueError('expected a list of cookie objects or a name-to-value object')

    exported_cookies = cast(list[RawExportedCookie], payload)

    return tuple(
        Cookie(
            name = exported_cookie['name'],
            value = exported_cookie['value'],
            domain = exported_cookie.get('domain') or DEFAULT_COOKIE_DOMAIN,
        )
        for exported_cookie in exported_cookies
    )

def parse_cookies(text: str) -> tuple[Cookie, ...]:
    stripped_text = text.strip()

    if stripped_text.startswith(('[', '{')):
        cookies = parse_json_cookies(json.loads(stripped_text))
    elif '\t' in stripped_text:
        cookies = parse_netscape_cookies(stripped_text)
    else:
        cookies = parse_cookie_header(stripped_text)

    return tuple(cookie for cookie in cookies if 'tiktok.com' in cookie.domain)

def read_cookie_file(path: Path) -> tuple[Cookie, ...]:
    try:
        cookies = parse_cookies(path.read_text(encoding = 'utf-8'))
    except OSError as E:
        raise CookieFileError(path, 'file could not be read') from E
    except (ValueError, KeyError, TypeError) as E:
        raise CookieFileError(path, f'unrecognised cookie format ({E})') from E

    if not cookies:
        raise CookieFileError(path, 'no tiktok.com cookies found')

    return cookies

def parse_dropped_path(text: str) -> Path:
    stripped_text = text.strip()

    if os.name == 'nt':
        return Path(stripped_text.strip('"'))

    try:
        parts = shlex.split(stripped_text)
    except ValueError:
        parts = [stripped_text]

    return Path(' '.join(parts)).expanduser()

def ensure_cookie_file(path: Path, read_line: Callable[[str], str] = input) -> Path:
    if path.exists():
        return path

    logger.warning('no cookie file found', expected = path.name)
    logger.info('drag your cookie file into this window, then press enter')

    try:
        dropped_text = read_line('> ')
    except (EOFError, KeyboardInterrupt) as E:
        raise CookieFileError(path, 'file does not exist and no file was provided') from E

    if not dropped_text.strip():
        raise CookieFileError(path, 'file does not exist and no file was provided')

    source_path = parse_dropped_path(dropped_text)
    cookies = read_cookie_file(source_path)

    if SESSION_COOKIE_NAME not in {cookie.name for cookie in cookies}:
        raise CookieFileError(source_path, f'no {SESSION_COOKIE_NAME} cookie, so it cannot log in; export it while logged in')

    try:
        path.write_text(source_path.read_text(encoding = 'utf-8'), encoding = 'utf-8')
        path.chmod(0o600)
    except OSError as E:
        raise CookieFileError(path, 'cookie file could not be saved') from E

    logger.info('saved cookie file', cookies = len(cookies), file = path.name)

    return path

def parse_session_user(raw_user: RawSessionUser | None) -> SessionUser | None:
    if not raw_user or not raw_user.get('uid'):
        return None

    return SessionUser(
        user_id = raw_user.get('uid', ''),
        handle = raw_user.get('uniqueId', ''),
        nickname = raw_user.get('nickName', ''),
        secure_user_id = raw_user.get('secUid', ''),
    )

def build_archive(
    handle: str,
    video_id: str,
    url: str,
    comments: Sequence[Comment],
    is_complete: bool,
    fetched_at: datetime,
) -> CommentArchive:
    return CommentArchive(
        handle = handle,
        video_id = video_id,
        url = url,
        fetched_at = fetched_at.isoformat(timespec = 'seconds'),
        is_complete = is_complete,
        comment_count = len(comments),
        replies_fetched = sum(len(comment.replies) for comment in comments),
        replies_expected = sum(comment.reply_count for comment in comments),
        comments = tuple(comments),
    )

def get_archive_path(directory: Path, handle: str, video_id: str) -> Path:
    return directory / f'{handle}_{video_id}.json'

def write_archive(archive: CommentArchive, directory: Path) -> Path:
    path = get_archive_path(directory, archive.handle, archive.video_id)

    try:
        directory.mkdir(parents = True, exist_ok = True)

        with path.open('w', encoding = 'utf-8') as file:
            json.dump(asdict(archive), file, indent = 2, ensure_ascii = False)
    except OSError as E:
        raise ArchiveWriteError(path) from E

    return path

logger = get_logger(__name__)

DEFAULT_COOKIE_DOMAIN = '.tiktok.com'
NETSCAPE_FIELD_COUNT = 7
SESSION_COOKIE_NAME = 'sessionid'
DATA_CENTRE_COOKIE_NAME = 'tt-target-idc'
KNOWN_DATA_CENTRES = ('us-eastred', 'eu-ttp2', 'useast5', 'useast2a', 'useast1a', 'alisg', 'no1a', 'maliva')
CSRF_HEADER = 'tt-csrf-token'
BLOCKED_HEADER = 'bdturing-verify'
LOG_ID_HEADER = 'x-tt-logid'

def parse_archived_comment(raw_comment: dict[str, Any]) -> Comment:
    replies = tuple(parse_archived_comment(raw_reply) for raw_reply in raw_comment.get('replies', []))

    return Comment(**{**raw_comment, 'replies': replies})

def read_archive(path: Path) -> CommentArchive:
    try:
        with path.open(encoding = 'utf-8') as file:
            raw_archive = cast(dict[str, Any], json.load(file))

        comments = tuple(parse_archived_comment(raw_comment) for raw_comment in raw_archive['comments'])

        return CommentArchive(**{**raw_archive, 'comments': comments})
    except OSError as E:
        raise ArchiveReadError(path, 'file could not be read') from E
    except (ValueError, KeyError, TypeError) as E:
        raise ArchiveReadError(path, f'unexpected archive format ({E})') from E

def create_session(cookie_path: Path | None = None, cookies: Sequence[Cookie] = ()) -> requests.Session:
    session = requests.Session(impersonate = 'chrome')

    try:
        loaded_cookies = read_cookie_file(cookie_path) if cookie_path is not None else tuple(cookies)
    except CookieFileError:
        session.close()
        raise

    for cookie in loaded_cookies:
        session.cookies.set(cookie.name, cookie.value, domain = cookie.domain)

    return session

def format_cookie_header(cookies: Sequence[Cookie]) -> str:
    return '; '.join(f'{cookie.name}={cookie.value}' for cookie in cookies)

def connect_login(
    cookies: Sequence[Cookie],
    session_factory: Callable[..., Any] = create_session,
) -> LoginResult:
    has_data_centre = any(cookie.name == DATA_CENTRE_COOKIE_NAME for cookie in cookies)
    candidates: list[tuple[Cookie, ...]] = [tuple(cookies)]

    if not has_data_centre:
        candidates += [(*cookies, Cookie(name = DATA_CENTRE_COOKIE_NAME, value = data_centre)) for data_centre in KNOWN_DATA_CENTRES]

    for candidate in candidates:
        with session_factory(cookies = candidate) as session:
            session_user = TikTokClient(cast(HttpSession, session)).get_session_user()

        if session_user is not None:
            if len(candidate) > len(cookies):
                logger.info('found the account data centre', data_centre = candidate[-1].value)

            return LoginResult(session_user = session_user, cookies = candidate)

    return LoginResult(session_user = None, cookies = tuple(cookies))

class TikTokClient:
    def __init__(
        self,
        session: HttpSession,
        config: FetchConfig = FetchConfig(),
        sleep: Callable[[float], None] = time.sleep,
        random_source: random.Random | None = None,
    ) -> None:
        self._session = session
        self._config = config
        self._sleep = sleep
        self._random_source = random_source or random.Random()

    def get_video_url(self, handle: str, video_id: str) -> str:
        return f'{self._config.base_url}/@{handle}/video/{video_id}'

    def get_profile(self, handle: str) -> Profile:
        url = f'{self._config.base_url}/@{handle}'
        state = extract_script_json(self._get(url).text, '__UNIVERSAL_DATA_FOR_REHYDRATION__', url)

        try:
            detail = cast(RawUserDetail, state['__DEFAULT_SCOPE__']['webapp.user-detail'])
        except KeyError as E:
            raise PageParseError(url, f'page state key {E} is missing') from E

        return parse_profile(detail, handle, url)

    def resolve_video(self, url: str) -> VideoReference:
        reference = parse_video_url(url)

        if reference is not None:
            return reference

        resolved_url = self._get(url).url
        reference = parse_video_url(resolved_url)

        if reference is None:
            raise VideoUrlError(url, resolved_url)

        logger.debug('resolved short link', video_id = reference.video_id, handle = reference.handle)

        return reference

    def get_app_context(self) -> RawAppContext:
        url = f'{self._config.base_url}/foryou'
        state = extract_script_json(self._get(url).text, '__UNIVERSAL_DATA_FOR_REHYDRATION__', url)

        try:
            return cast(RawAppContext, state['__DEFAULT_SCOPE__']['webapp.app-context'])
        except KeyError as E:
            raise PageParseError(url, f'page state key {E} is missing') from E

    def get_session_user(self) -> SessionUser | None:
        return parse_session_user(self.get_app_context().get('user'))

    def delete_comment(self, comment_id: str, referer: str | None = None) -> None:
        context = self.get_app_context()

        if parse_session_user(context.get('user')) is None:
            raise NotLoggedInError('delete a comment')

        url = f'{self._config.base_url}{ApiPath.COMMENT_DELETE.value}'
        headers = {
            CSRF_HEADER: context.get('csrfToken', ''),
            'referer': referer or f'{self._config.base_url}/',
        }

        try:
            response = self._session.post(
                url,
                params = {'aid': self._config.application_id, 'cid': comment_id},
                headers = headers,
                timeout = self._config.timeout_seconds,
            )
        except RequestException as E:
            raise TransportError(url) from E

        log_id = response.headers.get(LOG_ID_HEADER)

        if not response.content or response.headers.get(BLOCKED_HEADER):
            raise BlockedError(url, 'empty body or captcha challenge', log_id)

        try:
            result = cast(RawActionResult, response.json())
        except ValueError as E:
            raise PageParseError(url, 'response body is not valid JSON') from E

        if result.get('status_code') != 0:
            logger.error('delete failed', comment_id = comment_id, status_code = result.get('status_code'))
            raise DeleteFailedError(comment_id, result.get('status_code'), result.get('status_msg', ''), log_id)

        logger.info('deleted comment', comment_id = comment_id)

    def get_recent_videos(self, handle: str) -> tuple[Video, ...]:
        route = f'/embed/@{handle}'
        url = f'{self._config.base_url}{route}'
        state = extract_script_json(self._get(url).text, '__FRONTITY_CONNECT_STATE__', url)

        try:
            raw_videos = cast(list[RawEmbedVideo], state['source']['data'][route].get('videoList') or [])
        except KeyError as E:
            raise PageParseError(url, f'embed state key {E} is missing') from E

        return parse_videos(raw_videos, handle, self._config.base_url)

    def iter_comments(
        self,
        handle: str,
        video_id: str,
        limit: int | None = None,
        include_replies: bool = True,
    ) -> Iterator[Comment]:
        referer = self.get_video_url(handle, video_id)
        seen_comment_ids: set[str] = set()
        cursor = 0

        while True:
            with bind(handle = handle, video_id = video_id):
                page = self._get_comment_page(
                    ApiPath.COMMENT_LIST,
                    referer,
                    {'aweme_id': video_id, 'count': self._config.comment_page_size, 'cursor': cursor},
                )

            for raw_comment in page.get('comments') or []:
                if raw_comment['cid'] in seen_comment_ids:
                    continue

                seen_comment_ids.add(raw_comment['cid'])
                reply_count = raw_comment.get('reply_comment_total', 0)
                thread = ReplyThread(replies = (), expected_count = reply_count)

                if include_replies and reply_count:
                    with bind(handle = handle, video_id = video_id):
                        thread = self.get_reply_thread(handle, video_id, raw_comment['cid'], reply_count)

                yield parse_comment(raw_comment, replies = thread.replies, reply_count = thread.expected_count)

                if limit is not None and len(seen_comment_ids) >= limit:
                    return

            if not page.get('has_more'):
                return

            cursor = page.get('cursor', cursor + self._config.comment_page_size)

    def get_reply_thread(
        self,
        handle: str,
        video_id: str,
        comment_id: str,
        expected_count: int = 0,
    ) -> ReplyThread:
        referer = self.get_video_url(handle, video_id)
        page_size = self._config.reply_page_size
        seen_comment_ids: set[str] = set()
        replies: list[Comment] = []
        pages_fetched = 0
        cursor = 0

        while True:
            page = self._get_comment_page(
                ApiPath.REPLY_LIST,
                referer,
                {'item_id': video_id, 'comment_id': comment_id, 'count': page_size, 'cursor': cursor},
            )
            pages_fetched += 1
            expected_count = max(expected_count, page.get('total') or 0)
            page_ceiling = math.ceil(expected_count / page_size)
            new_replies = [
                raw_reply for raw_reply in page.get('comments') or []
                if raw_reply['cid'] not in seen_comment_ids
            ]

            for raw_reply in new_replies:
                seen_comment_ids.add(raw_reply['cid'])
                replies.append(parse_comment(raw_reply, parent_comment_id = comment_id))

            is_below_ceiling = len(seen_comment_ids) < expected_count and pages_fetched < page_ceiling
            has_more = bool(page.get('has_more')) or is_below_ceiling

            if not new_replies or not has_more:
                if len(replies) != expected_count:
                    logger.warning(
                        'reply count mismatch',
                        comment_id = comment_id,
                        fetched = len(replies),
                        expected = expected_count,
                    )

                return ReplyThread(replies = tuple(replies), expected_count = expected_count)

            cursor = page.get('cursor', cursor + page_size)

    def _get(
        self,
        url: str,
        parameters: Mapping[str, QueryValue] | None = None,
        referer: str | None = None,
    ) -> HttpResponse:
        headers = {'referer': referer} if referer else None

        try:
            return self._session.get(
                url,
                params = parameters,
                headers = headers,
                timeout = self._config.timeout_seconds,
            )
        except RequestException as E:
            raise TransportError(url) from E

    def _get_comment_page(
        self,
        path: ApiPath,
        referer: str,
        parameters: Mapping[str, QueryValue],
    ) -> RawCommentPage:
        url = f'{self._config.base_url}{path.value}'
        delay = self._random_source.uniform(
            self._config.minimum_delay_seconds,
            self._config.maximum_delay_seconds,
        )
        self._sleep(delay)
        response = self._get(url, {'aid': self._config.application_id, **parameters}, referer)
        log_id = response.headers.get(LOG_ID_HEADER)

        if not response.content or response.headers.get(BLOCKED_HEADER):
            logger.error('blocked by tiktok', path = path.value, log_id = log_id)
            raise BlockedError(url, 'empty body or captcha challenge', log_id)

        try:
            page = cast(RawCommentPage, response.json())
        except ValueError as E:
            raise PageParseError(url, 'response body is not valid JSON') from E

        if page.get('status_code') != 0:
            reason = f'status_code={page.get("status_code")} {page.get("status_msg", "")}'
            logger.error('request rejected', path = path.value, reason = reason)
            raise BlockedError(url, reason, log_id)

        logger.debug(
            'fetched page',
            path = path.value,
            cursor = parameters.get('cursor'),
            items = len(page.get('comments') or []),
        )

        return page
