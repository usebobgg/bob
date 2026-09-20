from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from fetch_comments import DATA_DIRECTORY, PROJECT_DIRECTORY, fetch_archive
from tiktok import (
    CommentArchive,
    DetectionConfig,
    FlaggedComment,
    HttpSession,
    LogConfig,
    TikTokClient,
    TikTokError,
    VideoReference,
    bind,
    configure_logging,
    create_session,
    detect_spam,
    ensure_cookie_file,
    get_archive_path,
    get_logger,
    read_archive,
)

MINIMUM_DELETE_DELAY_SECONDS = 3.0
MAXIMUM_DELETE_DELAY_SECONDS = 8.0
MAXIMUM_ARCHIVE_AGE = timedelta(hours = 12)

logger = get_logger('delete')

def parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = 'Delete flagged comments on one of your posts; dry run unless --confirm')
    parser.add_argument('url', help = 'link to your post: full video or photo link, or a short share link')
    parser.add_argument('--confirm', action = 'store_true', help = 'really delete; without this nothing is deleted')
    parser.add_argument('--refresh', action = 'store_true', help = 'ignore any saved archive and fetch again')
    parser.add_argument('--limit', type = int, help = 'delete at most this many comments in this run')
    parser.add_argument('--cookies', type = Path, default = PROJECT_DIRECTORY / 'cookies.txt')

    return parser.parse_args(arguments)

def get_progress_path(archive_path: Path) -> Path:
    return archive_path.with_suffix('.progress.json')

def read_deleted_ids(archive_path: Path) -> set[str]:
    try:
        return set(json.loads(get_progress_path(archive_path).read_text(encoding = 'utf-8'))['deleted_comment_ids'])
    except (OSError, ValueError, KeyError, TypeError):
        return set()

def write_deleted_ids(archive_path: Path, deleted_ids: set[str]) -> None:
    payload = {'deleted_comment_ids': sorted(deleted_ids)}
    get_progress_path(archive_path).write_text(json.dumps(payload, indent = 2), encoding = 'utf-8')

def retire_archive(archive_path: Path) -> None:
    done_directory = archive_path.parent / 'done'
    done_directory.mkdir(parents = True, exist_ok = True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')

    for path in (archive_path, get_progress_path(archive_path)):
        if path.exists():
            path.rename(done_directory / f'{stamp}_{path.name}')

def load_reusable_archive(archive_path: Path) -> CommentArchive | None:
    if not archive_path.exists():
        return None

    try:
        archive = read_archive(archive_path)
    except TikTokError as E:
        logger.warning('saved archive is unreadable', reason = str(E))
        return None

    age = datetime.now(timezone.utc) - datetime.fromisoformat(archive.fetched_at)

    if not archive.is_complete or age > MAXIMUM_ARCHIVE_AGE:
        logger.info('saved archive is stale', complete = archive.is_complete, age_hours = round(age.total_seconds() / 3600, 1))
        return None

    logger.info('using saved archive', file = archive_path.name, age_minutes = round(age.total_seconds() / 60))

    return archive

def get_archive(reference: VideoReference, archive_path: Path, should_refresh: bool) -> CommentArchive:
    archive = None if should_refresh else load_reusable_archive(archive_path)

    if archive is not None:
        return archive

    retire_archive(archive_path)

    with create_session() as anonymous_session:
        return fetch_archive(TikTokClient(cast(HttpSession, anonymous_session)), reference, archive_path.parent)

def log_flagged(flagged: Sequence[FlaggedComment]) -> None:
    for flagged_comment in flagged:
        logger.info(
            'flagged',
            author = flagged_comment.comment.handle,
            reason = '+'.join(reason.value for reason in flagged_comment.reasons),
            text = repr(flagged_comment.comment.text[:40]),
        )

def delete_flagged(
    client: TikTokClient,
    flagged: Sequence[FlaggedComment],
    referer: str,
    archive_path: Path,
    deleted_ids: set[str],
) -> int:
    deleted_count = 0

    for flagged_comment in flagged:
        comment = flagged_comment.comment

        with bind(author = comment.handle, text = comment.text, reasons = [reason.value for reason in flagged_comment.reasons]):
            try:
                client.delete_comment(comment.comment_id, referer = referer)
            except TikTokError as E:
                logger.error('stopping after failure', comment_id = comment.comment_id, reason = str(E))
                break

        deleted_count += 1
        deleted_ids.add(comment.comment_id)
        write_deleted_ids(archive_path, deleted_ids)

        if deleted_count < len(flagged):
            time.sleep(random.uniform(MINIMUM_DELETE_DELAY_SECONDS, MAXIMUM_DELETE_DELAY_SECONDS))

    return deleted_count

def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    configure_logging(LogConfig(file_path = PROJECT_DIRECTORY / 'logs' / 'bob.jsonl'))

    try:
        with create_session(ensure_cookie_file(options.cookies)) as session:
            client = TikTokClient(cast(HttpSession, session))
            session_user = client.get_session_user()

            if session_user is None:
                logger.error('login is not valid', cookies = options.cookies.name)
                return 1

            reference = client.resolve_video(options.url)

            if reference.handle != session_user.handle:
                logger.error('not your post', logged_in_as = session_user.handle, post_owner = reference.handle)
                return 1

            archive_path = get_archive_path(DATA_DIRECTORY, reference.handle, reference.video_id)
            archive = get_archive(reference, archive_path, options.refresh)

            if not archive.is_complete:
                logger.warning('archive is incomplete', note = 'detection may miss accounts')

            deleted_ids = read_deleted_ids(archive_path)
            report = detect_spam(archive.comments, DetectionConfig(excluded_user_ids = frozenset({session_user.user_id})))
            remaining = [flagged for flagged in report.flagged if flagged.comment.comment_id not in deleted_ids]
            batch = remaining[:options.limit] if options.limit is not None else remaining
            log_flagged(batch)

            if not options.confirm:
                logger.info('dry run, nothing deleted', would_delete = len(batch), remaining = len(remaining))
                return 0

            with bind(handle = archive.handle, video_id = archive.video_id):
                deleted_count = delete_flagged(client, batch, archive.url, archive_path, deleted_ids)
    except TikTokError as E:
        logger.error('delete run failed', reason = str(E))
        return 1

    left_count = len(remaining) - deleted_count
    logger.info('delete run finished', deleted = deleted_count, remaining = left_count)

    if left_count == 0:
        retire_archive(archive_path)
        logger.info('archive retired', note = 'next run fetches fresh comments')

    return 0 if deleted_count == len(batch) else 1

if __name__ == '__main__':
    sys.exit(main())
