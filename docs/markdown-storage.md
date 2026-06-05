# Markdown 存储设计

## 目标

将每集的观感访谈记录保存为 Markdown 文件，结构清晰，可直接导入 Obsidian。

## 目录结构

```
anime_notes/
│
├── 2026.4/                     # 2026年春季番
│   ├── 葬送的芙莉莲.md
│   └── 药屋少女的呢喃.md
│
├── 2025.10/                    # 2025年秋季番
│   ├── 某某番剧.md
│   └── ...
│
├── 2025.7/                     # 2025年夏季番
│   └── ...
│
└── 2025.1/                     # 2025年冬季番
    └── ...
```

- 第一层目录按**放送季度**划分，格式为 `{年份}.{季度起始月份}`
- 季度划分：1月（冬）、4月（春）、7月（夏）、10月（秋）
- 每个季度目录下，一部番剧对应**一个** `.md` 文件
- 文件名使用番剧中文名，若包含文件系统不允许的字符则做 sanitize 处理

## 季度判定规则

根据番剧的首播日期确定所属季度：

| 首播月份 | 季度 | 目录名 |
|---------|------|--------|
| 1-3月 | 冬季 | `{year}.1` |
| 4-6月 | 春季 | `{year}.4` |
| 7-9月 | 夏季 | `{year}.7` |
| 10-12月 | 秋季 | `{year}.10` |

判定依据优先级：
1. Bangumi 条目中的 `air_date` 字段
2. 用户手动指定

## 文件格式

```markdown
---
anime: 葬送的芙莉莲
bangumi_subject_id: 400602
season: 2026.4
total_episodes: 28
status: 在看
started_at: 2026-04-10
---

# 葬送的芙莉莲

## ep01

> **Q1:** 第一集给你留下了什么印象？
>
> **A1:** 芙莉莲的慢节奏叙事让我很意外，但又觉得很舒服...

## ep02

> **Q1:** 你觉得芙莉莲和辛美尔的关系在这一集有什么变化？
>
> **A2:** 她开始意识到时间对人类的意义了...

## ep15

> **Q1:** 很多观众讨论了芙莉莲对过去的理解变化。你认为这一集最打动你的地方是什么？
>
> **A1:** 我觉得芙莉莲回忆辛美尔的那段特别触动我...

> **Q2:** 你觉得芙莉莲对菲伦的态度和以前有什么不同？
>
> **A2:** 她现在更像一个真正的导师了...

## 总结

<!-- 由季度总结功能自动生成，或手动填写 -->

观看集数：15/28
最喜欢角色：芙莉莲
关键词：回忆、成长、师徒关系
```

## Frontmatter 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `anime` | string | 番剧中文名 |
| `bangumi_subject_id` | int | Bangumi 条目 ID |
| `season` | string | 放送季度，如 `2026.4` |
| `total_episodes` | int | 总集数 |
| `status` | string | 观看状态：在看 / 看完 / 搁置 / 抛弃 |
| `started_at` | date | 开始追番日期 |

## 单集章节格式

每集以 `## ep{集数}` 为二级标题，内容为该集的访谈问答：

```markdown
## ep15

> **Q1:** 问题内容
>
> **A1:** 回答内容

> **Q2:** 追问内容
>
> **A2:** 回答内容
```

- 访谈问答使用 blockquote 格式，Q/A 加粗
- 一轮访谈可能有多组 Q&A
- 同一集多次访谈（如重看）追加到同一 section 下，用分隔线 `---` 隔开

## 追番跨越季度的情况

如果一部番剧横跨两个季度（如 1 月开播、3 月完结），统一放到**首播季度**目录下。

## Obsidian 兼容性

使用 YAML frontmatter 格式，Obsidian 原生支持。

后续可利用 Obsidian 插件增强体验：

| 插件 | 用途 |
|------|------|
| Dataview | 按季度/状态/标签聚合查询，如 `TABLE FROM "anime_notes/2026.4"` |
| Calendar | 按日历视图查看观看历史 |
| Graph View | 通过标签建立不同番剧之间的关联图 |

## 实现接口

```python
# storage/markdown.py

from pathlib import Path

class MarkdownStorage:
    def __init__(self, base_dir: str = "anime_notes"):
        self._base_dir = Path(base_dir)

    def _get_season_dir(self, air_date: str) -> str:
        """根据首播日期计算季度目录名，如 '2026-04-10' -> '2026.4'"""
        ...

    def save_episode(
        self,
        anime_name: str,
        season: str,
        episode: int,
        qa_pairs: list[tuple[str, str]],  # [(question, answer), ...]
        subject_id: int = 0,
        total_episodes: int = 0,
    ) -> str:
        """保存单集观感到对应番剧文件，返回文件路径。

        若文件已存在，追加新的 ep section；
        若文件不存在，创建新文件并写入 frontmatter。
        """
        ...

    def load_anime(self, anime_name: str, season: str) -> str | None:
        """读取某番剧的完整文件内容"""
        ...

    def load_episode(self, anime_name: str, season: str, episode: int) -> str | None:
        """读取某番剧某集的 section 内容"""
        ...

    def list_seasons(self) -> list[str]:
        """列出所有季度目录，如 ['2026.4', '2025.10']"""
        ...

    def list_animes(self, season: str) -> list[str]:
        """列出某季度下所有番剧"""
        ...

    def append_summary(self, anime_name: str, season: str, summary: str) -> None:
        """追加或更新总结 section"""
        ...
```

## 文件读写策略

- **写入新集**：文件已存在时，找到最后一个 `## ep` section 的位置，在其后追加新 section
- **写入新番**：文件不存在时，创建文件并写入 frontmatter + 第一个 ep section
- **追加总结**：若已有 `## 总结` section 则替换内容，否则追加到文件末尾
- **编码**：统一使用 UTF-8

## 注意事项

1. **文件名 sanitize**：番剧名可能包含 `/`、`:`、`?` 等不允许的字符，替换为全角字符或 `_`
2. **并发写入**：MVP 阶段只有单用户，不存在并发问题
3. **同集多次记录**：同一集的多次访谈追加到同一 `## ep` section 下，用 `---` 分隔
4. **目录不存在**：写入前自动创建季度目录
5. **Markdown 解析**：按 `## ` 标题分割各集 section，写入时注意保持格式一致
