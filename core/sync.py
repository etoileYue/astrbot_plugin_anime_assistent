"""Bangumi 收藏同步 — 拉取「在看」列表到本地追番表。"""

import asyncio
import logging

from ..api.bangumi import BangumiClient
from ..storage.database import Database

logger = logging.getLogger(__name__)


async def sync_from_bangumi(db: Database, config) -> tuple[int, int, int, int, list[dict]]:
    """从 Bangumi 同步所有「在看」收藏到本地。以 Bangumi 数据为准覆盖本地。

    Returns:
        (总数, 新增数, 更新数, 删除数, progress_diffs)
        progress_diffs: 进度有变化的条目列表，每个 dict 含
            subject_id, subject_name, subject_name_cn, bangumi_eps, local_eps
    """
    client = BangumiClient(config)
    try:
        collections = await client.get_watching_collections()

        if not collections:
            logger.info("Bangumi「在看」列表为空，无需同步。")
            return (0, 0, 0, 0, [])

        existing = await db.list_subscriptions()
        existing_ids = {sub.subject_id for sub in existing}
        old_watched = {sub.subject_id: sub.watched_eps for sub in existing}

        newly_added = 0
        updated = 0
        progress_diffs: list[dict] = []
        bangumi_ids: set[int] = set()

        for item in collections:
            bangumi_ids.add(item.subject_id)
            is_new = item.subject_id not in existing_ids
            old_eps = old_watched.get(item.subject_id, 0)
            # 新增记录通过剧集数据推断番剧是否连载中；
            # 已存在记录不更新 airing（由调度器维护）。
            if is_new and item.eps > 0:
                try:
                    await asyncio.sleep(0.3)
                    episodes = await client.get_episodes(item.subject_id)
                    released = [ep for ep in episodes if ep.ep > 0 and (ep.name or ep.name_cn)]
                    if released:
                        latest_ep = max(ep.ep for ep in released)
                        airing = 0 if latest_ep >= item.eps else 1
                    else:
                        airing = 1
                except Exception:
                    logger.warning(f"获取 {item.subject_id} 剧集失败，默认标记为连载中")
                    airing = 1
            else:
                airing = 1

            await db.conn.execute(
                """INSERT INTO subscriptions
                   (subject_id, subject_name, subject_name_cn, total_eps, status, watched_eps, airing)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(subject_id) DO UPDATE SET
                   subject_name = excluded.subject_name,
                   subject_name_cn = excluded.subject_name_cn,
                   total_eps = excluded.total_eps,
                   status = excluded.status,
                   watched_eps = excluded.watched_eps""",
                (item.subject_id, item.subject_name, item.subject_name_cn, item.eps, 3, item.ep_status, airing),
            )

            if is_new:
                newly_added += 1
            elif item.ep_status != old_eps:
                updated += 1

            if item.ep_status > old_eps:
                progress_diffs.append({
                    "subject_id": item.subject_id,
                    "subject_name": item.subject_name,
                    "subject_name_cn": item.subject_name_cn,
                    "bangumi_eps": item.ep_status,
                    "local_eps": old_eps,
                })

            if item.subject_name_cn:
                await db.add_alias(item.subject_id, item.subject_name_cn)
            if item.subject_name:
                await db.add_alias(item.subject_id, item.subject_name)
            await db.add_alias(item.subject_id, str(item.subject_id))

        # 删除本地有但 Bangumi「在看」列表中没有的条目
        removed = 0
        stale_ids = existing_ids - bangumi_ids
        for sid in stale_ids:
            await db.conn.execute("DELETE FROM subscriptions WHERE subject_id = ?", (sid,))
            await db.conn.execute("DELETE FROM aliases WHERE subject_id = ?", (sid,))
            removed += 1

        await db.conn.commit()

        total = len(collections)
        logger.info(
            f"Bangumi 同步完成：新增 {newly_added}，更新 {updated}，删除 {removed}，共 {total}。"
            f"进度领先 {len(progress_diffs)} 部。"
        )
        return (total, newly_added, updated, removed, progress_diffs)
    finally:
        await client.close()
