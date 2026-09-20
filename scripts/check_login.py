from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from tiktok import (
    HttpSession,
    LogConfig,
    TikTokClient,
    TikTokError,
    configure_logging,
    create_session,
    ensure_cookie_file,
    get_logger,
)

PROJECT_DIRECTORY = Path(__file__).resolve().parent.parent

logger = get_logger('login')

def parse_arguments(arguments: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = 'Check whether the TikTok login in a cookie file is valid')
    parser.add_argument('--cookies', type = Path, default = PROJECT_DIRECTORY / 'cookies.txt')

    return parser.parse_args(arguments)

def main(arguments: Sequence[str] | None = None) -> int:
    options = parse_arguments(arguments)
    configure_logging(LogConfig(file_path = PROJECT_DIRECTORY / 'logs' / 'bob.jsonl'))

    try:
        with create_session(ensure_cookie_file(options.cookies)) as session:
            session_user = TikTokClient(cast(HttpSession, session)).get_session_user()
    except TikTokError as E:
        logger.error('login check failed', reason = str(E))
        return 1

    if session_user is None:
        logger.error('login is not valid', cookies = options.cookies.name)
        return 1

    logger.info('login is valid', handle = session_user.handle, user_id = session_user.user_id)

    return 0

if __name__ == '__main__':
    sys.exit(main())
