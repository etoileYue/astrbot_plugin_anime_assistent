"""Bangumi 收藏同步 — 拉取「在看」列表到本地追番表。"""

import asyncio
import logging

from ..api.bangumi import BangumiClient, CollectionType
from ..storage.database import Database

logger = logging.getLogger(__name__)


async def sync_from_bangumi(db: Database, config) -> tuple[int, int, int, int, list[dict]]:
    """从 Bangumi 同步所有「在看」收藏到本地。以 Bangumi 数据为准覆盖本地。

    Returns:
        (总数, 新增数, 更新数, 删除数, progress_diffs)
        progress_diffs: 进度有变化的条目列表，每个 dict 含
            subject_id, subject_name, subject_name_cn, start_episode, end_episode
    """
    client = BangumiClient(config)
    try:
        collections = await client.get_watching_collections()

        if not collections:
            logger.info("Bangumi「在看」列表为空，继续检查是否有已看完条目。")

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
            # 更新提醒由 Tenrai 排期决定；不再通过 Bangumi 分集接口推断连载状态。
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
                    "start_episode": old_eps + 1,
                    "end_episode": item.ep_status,
                    "bangumi_eps": item.ep_status,
                    "local_eps": old_eps,
                })

            if item.subject_name_cn:
                await db.add_alias(item.subject_id, item.subject_name_cn)
            if item.subject_name:
                await db.add_alias(item.subject_id, item.subject_name)
            await db.add_alias(item.subject_id, str(item.subject_id))

        # 删除本地有但 Bangumi「在看」列表中没有的条目
        # 但如果条目是被移入「看过」(type=2)，说明用户已看完，仍需触发访谈。
        removed = 0
        stale_ids = existing_ids - bangumi_ids
        for sid in stale_ids:
            try:
                await asyncio.sleep(0.5)
                coll = await client.get_collection(sid)
                if coll and coll.get("type") == CollectionType.DONE:
                    sub = next((s for s in existing if s.subject_id == sid), None)
                    old_eps = old_watched.get(sid, 0)
                    bangumi_eps = coll.get("ep_status", 0) or 0
                    subject = coll.get("subject") or {}
                    known_total = max(
                        sub.total_eps if sub else 0,
                        subject.get("eps", 0) or 0,
                    )
                    # 标为“看过”时，ep_status 可能未回传；此时总集数代表完成进度。
                    episode = max(bangumi_eps, known_total)
                    if episode > old_eps:
                        progress_diffs.append({
                            "subject_id": sid,
                            "subject_name": sub.subject_name if sub else "",
                            "subject_name_cn": sub.subject_name_cn if sub else "",
                            "start_episode": old_eps + 1,
                            "end_episode": episode,
                            "bangumi_eps": episode,
                            "local_eps": old_eps,
                        })
                        logger.info(
                            f"条目 {sid} 已从「在看」移出并标记为看过，"
                            f"进度 {old_eps} → {episode}，触发访谈"
                        )
            except Exception as e:
                logger.warning(
                    f"检查已移除条目 {sid} 的收藏状态失败: "
                    f"{e.__class__.__name__}: {e}"
                )

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
