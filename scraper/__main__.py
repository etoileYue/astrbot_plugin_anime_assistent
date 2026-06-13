"""独立运行爬虫模块，验证评论抓取结果。

用法：python -m scraper <episode_id> [--limit N] [--no-cache] [--cn-mirror]
示例：python -m scraper 12345
      python -m scraper 12345 --limit 10
      python -m scraper 12345 --no-cache
      python -m scraper 12345 --cn-mirror  # 使用国内镜像
"""

import argparse
import asyncio
import logging
import sys

from scraper.bangumi import BangumiScraper

logger = logging.getLogger("scraper")


def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def print_comments(episode_id: int, comments, cached: bool):
    print(f"\n{'='*60}")
    print(f"剧集 ID: {episode_id}")
    print(f"来源: {'缓存' if cached else '远程爬取'}")
    print(f"评论数: {len(comments)}")
    print(f"{'='*60}\n")

    if not comments:
        print("（暂无评论）")
        return

    for i, c in enumerate(comments, 1):
        print(f"#{c.floor}  {c.username}  {c.timestamp}")
        print(f"  {c.text}")
        print()


async def main():
    parser = argparse.ArgumentParser(description="Bangumi 剧集评论爬虫")
    parser.add_argument("episode_id", type=int, help="剧集 ID（可从 Bangumi 剧集页 URL 获取）")
    parser.add_argument("--limit", "-n", type=int, default=30, help="最大评论数（默认 30）")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制重新爬取")
    parser.add_argument("--cn-mirror", action="store_true", help="使用国内镜像 https://bangumi.one")
    args = parser.parse_args()

    setup_logging()

    scraper = BangumiScraper(use_cn_mirror=args.cn_mirror)

    try:
        if args.no_cache:
            scraper._cache.pop(args.episode_id, None)

        # 检查缓存
        cached = args.episode_id in scraper._cache

        comments = await scraper.get_episode_comments(args.episode_id, limit=args.limit)
        print_comments(args.episode_id, comments, cached)

    except KeyboardInterrupt:
        print("\n已取消")
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
