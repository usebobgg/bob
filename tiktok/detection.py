from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import Enum

from tiktok.logger import get_logger
from tiktok.models import Comment

__all__ = [
    'DetectionConfig',
    'DetectionReport',
    'FlagReason',
    'FlaggedComment',
    'detect_spam',
    'find_duplicate_replies',
    'find_excessive_repliers',
    'iter_all_comments',
    'normalise_text',
]

logger = get_logger(__name__)

class FlagReason(Enum):
    DUPLICATE_REPLY = 'duplicate_reply'
    EXCESSIVE_REPLIES = 'excessive_replies'

@dataclass(frozen = True)
class DetectionConfig:
    minimum_duplicate_parents: int = 2
    maximum_distinct_parents: int = 3
    excluded_user_ids: frozenset[str] = frozenset()

@dataclass(frozen = True)
class FlaggedComment:
    comment: Comment
    reasons: tuple[FlagReason, ...]

@dataclass(frozen = True)
class DetectionReport:
    flagged: tuple[FlaggedComment, ...]
    flagged_user_ids: frozenset[str]
    comments_scanned: int
    replies_scanned: int

    @property
    def flagged_comment_ids(self) -> tuple[str, ...]:
        return tuple(flagged_comment.comment.comment_id for flagged_comment in self.flagged)

def normalise_text(text: str) -> str:
    return ' '.join(text.casefold().split())

def iter_all_comments(comments: Sequence[Comment]) -> Iterator[Comment]:
    for comment in comments:
        yield comment
        yield from comment.replies

def is_scannable(comment: Comment, config: DetectionConfig) -> bool:
    return comment.user_id is not None and comment.user_id not in config.excluded_user_ids

def find_duplicate_replies(comments: Sequence[Comment], config: DetectionConfig) -> frozenset[str]:
    parents_by_reply_text: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    reply_ids_by_reply_text: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

    for comment in comments:
        for reply in comment.replies:
            if not is_scannable(reply, config) or reply.user_id is None:
                continue

            key = (reply.user_id, normalise_text(reply.text))
            parents_by_reply_text[key].add(comment.comment_id)
            reply_ids_by_reply_text[key].add(reply.comment_id)

    return frozenset(
        reply_id
        for key, parent_ids in parents_by_reply_text.items()
        if len(parent_ids) >= config.minimum_duplicate_parents
        for reply_id in reply_ids_by_reply_text[key]
    )

def find_excessive_repliers(comments: Sequence[Comment], config: DetectionConfig) -> frozenset[str]:
    parents_by_user: defaultdict[str, set[str]] = defaultdict(set)

    for comment in comments:
        for reply in comment.replies:
            if not is_scannable(reply, config) or reply.user_id is None:
                continue

            parents_by_user[reply.user_id].add(comment.comment_id)

    return frozenset(
        user_id
        for user_id, parent_ids in parents_by_user.items()
        if len(parent_ids) > config.maximum_distinct_parents
    )

def get_flag_reasons(
    comment: Comment,
    duplicate_reply_ids: frozenset[str],
    excessive_user_ids: frozenset[str],
) -> tuple[FlagReason, ...]:
    reasons: list[FlagReason] = []

    if comment.comment_id in duplicate_reply_ids:
        reasons.append(FlagReason.DUPLICATE_REPLY)

    if comment.user_id in excessive_user_ids:
        reasons.append(FlagReason.EXCESSIVE_REPLIES)

    return tuple(reasons)

def detect_spam(comments: Sequence[Comment], config: DetectionConfig = DetectionConfig()) -> DetectionReport:
    duplicate_reply_ids = find_duplicate_replies(comments, config)
    excessive_user_ids = find_excessive_repliers(comments, config)
    flagged: list[FlaggedComment] = []

    for comment in iter_all_comments(comments):
        reasons = get_flag_reasons(comment, duplicate_reply_ids, excessive_user_ids)

        if reasons:
            flagged.append(FlaggedComment(comment = comment, reasons = reasons))

    report = DetectionReport(
        flagged = tuple(flagged),
        flagged_user_ids = frozenset(
            flagged_comment.comment.user_id
            for flagged_comment in flagged
            if flagged_comment.comment.user_id is not None
        ),
        comments_scanned = len(comments),
        replies_scanned = sum(len(comment.replies) for comment in comments),
    )
    logger.info(
        'detection finished',
        flagged = len(report.flagged),
        users = len(report.flagged_user_ids),
        scanned = report.comments_scanned + report.replies_scanned,
    )

    return report
