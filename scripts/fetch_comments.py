from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from tiktok import (
    BlockedError,
    Comment,
    CommentArchive,
    HttpSession,
    LogConfig,
    LogLevel,
    TikTokClient,
    TikTokError,
    VideoReference,
    bind,
    build_archive,
    configure_logging,
    create_session,
    get_logger,
    write_archive,
)

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent
DATA_DIRECTORY = PROJECT_DIRECTORY / 'data'

logger = get_logger('fetch')

def parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = 'Fetch every comment and reply on one TikTok post')
    parser.add_argument('url', help = 'post link: full video or photo link, or a short share link')
    parser.add_argument('--limit', type = int, help = 'stop after this many top-level comments')
    parser.add_argument('--cookies', type = Path, help = 'fetch as a logged-in user; anonymous when omitted')
    parser.add_argument('--output', type = Path, default = DATA_DIRECTORY)
    parser.add_argument('--verbose', action = 'store_true', help = 'show every page request')

    return parser.parse_args(arguments)

def collect_comments(
    client: TikTokClient,
    handle: str,
    video_id: str,
    limit: int | None,
    on_comment: Callable[[Comment], None] | None = None,
) -> tuple[list[Comment], bool]:
    comments: list[Comment] = []

    try:
        for comment in client.iter_comments(handle, video_id, limit = limit):
            comments.append(comment)

            if on_comment is not None:
                on_comment(comment)

            logger.info(
                'fetched comment',
                number = len(comments),
                author = comment.handle,
                replies = f'{len(comment.replies)}/{comment.reply_count}',
            )
    except BlockedError as E:
        logger.error('stopped early', reason = E.reason)
        return comments, False

    return comments, limit is None

def fetch_archive(
    client: TikTokClient,
    reference: VideoReference,
    output_directory: Path,
    limit: int | None = None,
    on_comment: Callable[[Comment], None] | None = None,
) -> CommentArchive:
    handle = reference.handle or ''

    with bind(handle = handle, video_id = reference.video_id):
        logger.info('fetching comments', handle = handle, video_id = reference.video_id)
        comments, is_complete = collect_comments(client, handle, reference.video_id, limit, on_comment)
        archive = build_archive(
            handle = handle,
            video_id = reference.video_id,
            url = reference.url,
            comments = comments,
            is_complete = is_complete,
            fetched_at = datetime.now(timezone.utc),
        )
        path = write_archive(archive, output_directory)

    logger.info(
        'saved archive',
        comments = archive.comment_count,
        replies = f'{archive.replies_fetched}/{archive.replies_expected}',
        file = path.name,
    )

    return archive

def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    level = LogLevel.DEBUG if options.verbose else LogLevel.INFO
    configure_logging(LogConfig(level = level, file_path = PROJECT_DIRECTORY / 'logs' / 'bob.jsonl'))

    try:
        with create_session(options.cookies) as session:
            client = TikTokClient(cast(HttpSession, session))
            reference = client.resolve_video(options.url)

            if reference.handle is None:
                logger.error('link has no handle', url = reference.url)
                return 1

            archive = fetch_archive(client, reference, options.output, options.limit)
    except TikTokError as E:
        logger.error('fetch failed', reason = str(E))
        return 1

    return 0 if archive.is_complete or options.limit is not None else 1

if __name__ == '__main__':
    sys.exit(main())
