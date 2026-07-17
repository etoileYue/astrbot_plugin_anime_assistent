# ADR-007：将自动排期提供方从 Jikan 切换为 Tenrai

## 背景

Jikan 在排期查询时依赖连接 MyAnimeList。运行中出现 Jikan 返回 504，提示其无法连接 MAL，导致追番排期无法补齐。

## 决策

自动排期查询改用 Tenrai API v1（`https://api.tenrai.org/v1`）的 `GET /anime` 搜索端点。继续只取前五项，且仅接受经 Unicode NFKC 规范化、删除全部空白字符后与 Bangumi 日文原名完全一致的 `title_japanese`。继续使用返回的 `broadcast.day`、`broadcast.time`、`broadcast.timezone` 转换并保存北京时间。

## 原因

- Tenrai v1 官方文档声明兼容 Jikan v4 的端点和响应结构，因此可在不降低匹配准确性的前提下替换提供方。
- Tenrai 的数据由自身缓存提供，避免请求期间由 Jikan 再向 MAL 建立连接。
- 公开访问无需密钥；插件仍以每秒一次的保守频率请求，低于其公共额度。

## 替代方案

- 等待 Jikan/MAL 上游故障恢复：不能解决当前排期补齐失败。
- 仅使用手动排期：可靠但增加用户维护成本。
- 直接使用 MyAnimeList API：需要额外 OAuth 认证，且超出插件当前需求。

## 影响

- `api/jikan.py` 被 `api/tenrai.py` 替代。
- `/sub schedule auto` 和 `/sync` 会经由 Tenrai 查询；手动设置与历史数据库字段不变。
- Tenrai 仍是 beta 公共 API，网络和 429/5xx 重试逻辑必须保留。
