"""Bangumi 收藏同步 — 拉取「在看」列表到本地追番表。"""

import logging

from ..api.bangumi import BangumiClient
from ..storage.database import Database

logger = logging.getLogger(__name__)


async def sync_from_bangumi(db: Database, config) -> tuple[int, int]:
    """从 Bangumi 同步所有「在看」收藏到本地。

    Returns:
        (总数, 新增数)
    """
    client = BangumiClient(config)
    try:
        collections = await client.get_watching_collections()
    finally:
        await client.close()

    if not collections:
        logger.info("Bangumi「在看」列表为空，无需同步。")
        return (0, 0)

    existing = await db.list_subscriptions()
    existing_ids = {sub.subject_id for sub in existing}

    newly_added = 0
    for item in collections:
        is_new = item.subject_id not in existing_ids
        await db.conn.execute(
            """INSERT OR IGNORE INTO subscriptions
               (subject_id, subject_name, subject_name_cn, total_eps, status, watched_eps)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item.subject_id, item.subject_name, item.subject_name_cn, item.eps, 3, item.ep_status),
        )
        if is_new:
            newly_added += 1
        await db.update_watched_eps(item.subject_id, item.ep_status)

        if item.subject_name_cn:
            await db.add_alias(item.subject_id, item.subject_name_cn)
        if item.subject_name:
            await db.add_alias(item.subject_id, item.subject_name)
        await db.add_alias(item.subject_id, str(item.subject_id))

    await db.conn.commit()

    total = len(collections)
    logger.info(f"Bangumi 同步完成：新增 {newly_added}，已有 {total - newly_added}，共 {total}。")
    return (total, newly_added)
