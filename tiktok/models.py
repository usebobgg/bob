from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple, Protocol, Required, TypedDict

__all__ = [
    'ApiPath',
    'ArchiveReadError',
    'ArchiveWriteError',
    'BlockedError',
    'Comment',
    'CommentArchive',
    'Cookie',
    'CookieFileError',
    'DeleteFailedError',
    'FetchConfig',
    'HttpResponse',
    'HttpSession',
    'NotLoggedInError',
    'PageParseError',
    'Profile',
    'ProfileUnavailableError',
    'QueryValue',
    'RawActionResult',
    'RawAppContext',
    'RawComment',
    'RawCommentPage',
    'RawCommentUser',
    'RawEmbedVideo',
    'RawExportedCookie',
    'RawProfileStats',
    'RawProfileUser',
    'RawSessionUser',
    'RawUserDetail',
    'RawUserInfo',
    'ReplyThread',
    'SessionUser',
    'TikTokError',
    'TransportError',
    'Video',
    'VideoReference',
    'VideoUrlError',
]

class RawCommentUser(TypedDict, total = False):
    uid: str
    unique_id: str
    nickname: str

class RawComment(TypedDict, total = False):
    cid: Required[str]
    aweme_id: str
    text: str
    create_time: int
    digg_count: int
    reply_comment_total: int
    image_list: list[object] | None
    user: RawCommentUser

class RawCommentPage(TypedDict, total = False):
    status_code: int
    status_msg: str
    comments: list[RawComment] | None
    cursor: int
    has_more: int
    total: int

class RawProfileUser(TypedDict, total = False):
    id: Required[str]
    secUid: Required[str]
    uniqueId: Required[str]
    nickname: Required[str]
    signature: str
    verified: bool
    privateAccount: bool

class RawProfileStats(TypedDict):
    followerCount: int
    followingCount: int
    heartCount: int
    videoCount: int

class RawUserInfo(TypedDict):
    user: RawProfileUser
    stats: RawProfileStats

class RawUserDetail(TypedDict, total = False):
    statusCode: int
    userInfo: RawUserInfo

class RawAppContext(TypedDict, total = False):
    csrfToken: str
    user: RawSessionUser | None

class RawActionResult(TypedDict, total = False):
    status_code: int
    status_msg: str

class RawSessionUser(TypedDict, total = False):
    uid: str
    uniqueId: str
    nickName: str
    secUid: str

class RawExportedCookie(TypedDict, total = False):
    name: Required[str]
    value: Required[str]
    domain: str

class RawEmbedVideo(TypedDict, total = False):
    id: Required[str]
    desc: str
    playCount: int

class ApiPath(str, Enum):
    COMMENT_LIST = '/api/comment/list/'
    REPLY_LIST = '/api/comment/list/reply/'
    COMMENT_DELETE = '/api/comment/delete/'

@dataclass(frozen = True)
class FetchConfig:
    base_url: str = 'https://www.tiktok.com'
    application_id: int = 1988
    comment_page_size: int = 20
    reply_page_size: int = 20
    minimum_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 2.5
    timeout_seconds: int = 30

@dataclass(frozen = True)
class Profile:
    user_id: str
    secure_user_id: str
    handle: str
    nickname: str
    biography: str
    is_verified: bool
    is_private: bool
    follower_count: int
    following_count: int
    like_count: int
    video_count: int

@dataclass(frozen = True)
class Video:
    video_id: str
    description: str
    play_count: int | None
    url: str

@dataclass(frozen = True)
class Comment:
    comment_id: str
    parent_comment_id: str | None
    video_id: str | None
    text: str
    created_at: int | None
    like_count: int
    reply_count: int
    has_image: bool
    user_id: str | None
    handle: str | None
    nickname: str | None
    replies: tuple[Comment, ...] = ()

@dataclass(frozen = True)
class CommentArchive:
    handle: str
    video_id: str
    url: str
    fetched_at: str
    is_complete: bool
    comment_count: int
    replies_fetched: int
    replies_expected: int
    comments: tuple[Comment, ...]

@dataclass(frozen = True)
class Cookie:
    name: str
    value: str
    domain: str = '.tiktok.com'

@dataclass(frozen = True)
class SessionUser:
    user_id: str
    handle: str
    nickname: str
    secure_user_id: str

class VideoReference(NamedTuple):
    handle: str | None
    video_id: str
    url: str

class ReplyThread(NamedTuple):
    replies: tuple[Comment, ...]
    expected_count: int

class TikTokError(Exception):
    ...

class TransportError(TikTokError):
    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f'Request failed: {url}')

class BlockedError(TikTokError):
    def __init__(self, url: str, reason: str, log_id: str | None = None) -> None:
        self.url = url
        self.reason = reason
        self.log_id = log_id
        super().__init__(f'Blocked by TikTok at {url}: {reason} (log id {log_id})')

class PageParseError(TikTokError):
    def __init__(self, url: str, detail: str) -> None:
        self.url = url
        self.detail = detail
        super().__init__(f'Could not parse {url}: {detail}')

class ProfileUnavailableError(TikTokError):
    def __init__(self, handle: str, status_code: int | None) -> None:
        self.handle = handle
        self.status_code = status_code
        super().__init__(f'Profile @{handle} is unavailable (status code {status_code})')

class ArchiveWriteError(TikTokError):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f'Could not write archive: {path}')

QueryValue = str | int

class ArchiveReadError(TikTokError):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f'Could not read archive {path}: {detail}')

class CookieFileError(TikTokError):
    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f'Could not load cookies from {path}: {detail}')

class VideoUrlError(TikTokError):
    def __init__(self, url: str, resolved_url: str | None = None) -> None:
        self.url = url
        self.resolved_url = resolved_url
        super().__init__(f'No video id found in {url} (resolved to {resolved_url})')

class NotLoggedInError(TikTokError):
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(f'A logged-in session is required to {action}')

class DeleteFailedError(TikTokError):
    def __init__(self, comment_id: str, status_code: int | None, message: str, log_id: str | None = None) -> None:
        self.comment_id = comment_id
        self.status_code = status_code
        self.log_id = log_id
        super().__init__(f'Could not delete comment {comment_id}: status_code={status_code} {message} (log id {log_id})')

class HttpResponse(Protocol):
    @property
    def url(self) -> str: ...

    @property
    def content(self) -> bytes: ...

    @property
    def text(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str | None]: ...

    def json(self) -> Any: ...

class HttpSession(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
    ) -> HttpResponse: ...

    def post(
        self,
        url: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
    ) -> HttpResponse: ...
