# ADR-003: 使用 AstrBot 内置 LLM Provider 系统

## 背景

访谈功能需要调用 LLM 生成问题和追问。需要决定是直接调用 LLM API（OpenAI/Claude SDK）还是使用 AstrBot 内置的 LLM 调用能力。

## 决策

通过 AstrBot 的 Provider 系统调用 LLM（`provider.text_chat()`），不直接调用外部 LLM API。

## 原因

- **统一配置**：用户已在 AstrBot WebUI 中配置 LLM provider，无需在插件中重复配置 API key
- **Provider 可替换**：用户可随时切换 OpenAI / Claude / Gemini / DeepSeek，插件代码无需修改
- **会话上下文**：AstrBot provider 支持上下文管理，便于多轮访谈对话
- **AstrBot 生态兼容**：如果未来 AstrBot 增加 LLM 调用增强（如缓存、路由），插件自动受益
- **减少依赖**：不需要在 `requirements.txt` 中添加 openai / anthropic SDK

## 替代方案

| 方案 | 评估 |
|------|------|
| 直接调用 OpenAI/Claude API | 需要在插件配置中管理 API key，与 AstrBot LLM 配置重复 |
| 通过 `context.llm_generate()` | 更简洁但需要 >= v4.5.7；`provider.text_chat()` 兼容更广 |
| LLM 完全可选 | 无 LLM 则访谈功能无法工作，不符合设计目标 |

## 影响

- `llm/client.py` 封装 AstrBot provider 调用，提供 `generate()` 和 `chat()` 两个方法
- 依赖 AstrBot 已配置 LLM provider，否则访谈功能静默降级（返回空字符串）
- 不引入额外的 LLM SDK 依赖
