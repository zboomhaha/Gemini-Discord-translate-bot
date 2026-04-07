<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737963243834_walmart_papago_logo.png" width="200" height="200" /></div>
<div align="center">
<h1><strong>Walmart Papago Discord translation bot</strong></h1>
</div>
<div align="center">
    <a href="https://github.com/zboomhaha/Walmart-Papago/blob/main/README-EN.md">English</a>
</div>
<br>
<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737972141929_ezgif-7-2bcd85fa0a55_1.gif" width="700" /></div>
<br>

## 📄**项目简介**

Walmart Papago 是一款自部署的、Gemini驱动的Discord翻译机器人，能够实时翻译指定频道里的文本、图像、embed消息。<br>适应Discord特性，分段返回原文、翻译和注释，方便复制粘贴。

## 💡**功能亮点**

### **1. 丰富的Slash Commands**

- **灵活的翻译频道配置：**（A→A或A→B或A、B→C均可）。
- **自定义术语、忽略特定关键词：** 使用Slash Commands直接管理相关词典，配置热更新。
- **频道内翻译对象管理：** 支持阻止特定用户/Bot/Webhook的消息被翻译。

### **2. 智能内容处理**

- **多格式内容解析：** 支持`普通文本`、`附件图片`、`Embed` 、`引用消息`、`FxTwitter`等多种内容格式的翻译。（处理引用消息时，bot需要拥有读取该消息源频道的权限）
- **内容预过滤：** 预过滤仅包含Emoji/Discord自定义表情/中英标点符号/纯数字/空内容的自然行，避免输出多余的翻译内容。
- **自动包裹URL：** 自动识别并使用```包裹URL，避免FIX-URL类的Discord Bot重复识别URL并展开URL内容。

### **3. 负载均衡优化**

- **三层 Fallback 机制：** Key 失败 → 随机换 Key（最多 3 次）→ Model Cooldown 切换备用 Model → Provider Fallback 切换备用服务商。
- **智能错误分级：** 503 立即触发 5 分钟 Model Cooldown；429 随机换 Key 重试；400/403 自动禁用 Key 并发送 Webhook 告警（附带 Key 信息）。
- **Per-Key RPM 限速：** RPM 配置作用于单个 Key，多 Key 并行时速率互不干扰。
- **任务级精细化超时：** 采用原子化计时策略。文字翻译 (60s) 与图片翻译 (90s) 独立计时，且计时仅覆盖 API 交互阶段。Discord 消息发送等异步 I/O 不占用翻译时间配额。
- **全局 600s 兜底保护：** 宽裕的全局超时限制（10分钟）仅用于死锁自愈。
- **自适应并发控制：** 内置消息去重与缓存机制，异步消息队列确保消息顺序。
- **自动轮转和清理日志：** 日志文件每日自动轮转，自动清理超过7天的记录。

### **4. Default Language=zh-CN的彩蛋**

- **中文小标题：** 翻译反馈中的小标题将以简体中文来显示，否则默认显示英文。（如：“文字翻译”&“Text Translation”）
- **智能跳过中文行：** 如果单行中的中文占比超过50%，则该行不会被提交至Gemini进行翻译。

## 📅**更新日志**

### **2026-04-08: 自定义 Provider 鲁棒性重构与错误收集系统**
- **接口兼容性跃迁 (Dual-Auth)：** 实现了 API Key 的“双投递”鉴权（同时发送 URL 参数和 `x-goog-api-key` Header），解决了部分中转服务商因未透传 URL 参数导致的 `401 Unauthorized` 问题。
- **全方位响应验证 (Response Guardian)：** 引入了对 `text/html` 响应的严格检测。当 API 返回 Cloudflare 验证页面或错误路径导致的 HTML 时，机器人会提取 HTML 标题并抛出明确错误，不再发生“静默失败”返回空内容。
- **重定向与内部错误拦截：** 增加了对 3xx 重定向的显式检测，并针对部分 API 在 HTTP 200 下返回包含 `error` 字段的 JSON 结构进行了防护处理。
- **错误收集系统：** 彻底重构了翻译子任务的管理逻辑。对于同一条消息中的多个翻译请求（文本、Embed、FxTwitter、多附件图片），机器人现在会并行/串行执行并收集所有异常。哪怕其中一张图片由于 OCR 失败，其他部分的翻译仍会继续，且仅在所有部分均失败时才发送综合 Webhook 告警，显著降低了报错噪音。
- **启动连通性自检 (Startup Health Check)：** 机器人启动时新增对所有自定义 Provider 的连通性测试。若发现由于 Base URL 配置不当（如使用了 OpenAI 格式而非 Gemini 格式）导致的失败，将在日志中给出明确提醒。

### **2026-03-13: Prompt 指令精细化与排版逻辑优化**
- **Prompt 深度审计与修复：** 对 `TRANSLATION_PROMPT` 和 `IMAGE_TRANSLATION_PROMPT` 进行了全面审查。修复了关于“保留原始段落结构”与“处理断行”之间的指令矛盾，并消除了 Notes 区域中“添加注释”与“禁止解释词汇”的逻辑冲突。
- **冗余指令清理：** 合并了多处关于准确性、可读性以及 Glossary 映射的重复规则，精简了早期的 Roleplay 冗余描述，在维持翻译质量的同时降低了 Token 消耗并提升了模型对指令的遵循度。
- **图像上下文校验：** 优化了图片翻译中的来源上下文识别指令，使模型在处理社交媒体截图、文章或聊天记录时能更准确地匹配语境。

### **2026-03-13: 翻译任务独立超时与稳定性增强**
- **任务级独立超时：** 彻底重构了翻译任务计时逻辑，将单条 Discord 消息的文字翻译 (60s) 与图片翻译 (90s) 的超时计时器解除耦合。即使同一条消息包含大量图文链接（如 FxTwitter），各子任务也会独立计算计时，避免因 API 延迟累加导致的整体意外中断。
- **计时口径优化：** 改进了超时计算的终点。现在计时仅截止到模型成功返回响应（翻译内容或 200 OK）为止，昂贵的 Discord 消息发送 I/O 不再计入翻译超时预算。
- **全局死锁保险丝：** 将全局 `handle_message` 超时大幅放宽至 10 分钟（600s），该限制仅作为防止代码死循环或死锁的最后一道保险，正常翻译流程不再受此限制约束。
- **消息切分优化：** 优化了长文本和注释（Notes）的消息切分逻辑，确保在处理超长响应时能更平滑地分段发送至 Discord。

### **2025-03-05: Fallback 机制重构**
- **智能错误分级处理：** 根据 HTTP 状态码精细化处理不同错误类型：503（模型过载）立即切换 Model 并进入 5 分钟 Cooldown；429（配额超限）随机换 Key 重试；400/403（Key 失效）自动禁用 Key 并发送 Webhook 通知管理员。
- **Per-Key RPM 限制：** RPM 速率限制从 Provider 级别细化至单个 Key 级别，多 Key 之间不再互相干扰速率。
- **随机 Key 选择：** 放弃固定轮询，改为随机选取可用 Key，避免热点。
- **双层超时保护：** 单次 API 调用超时 10-20 秒（快速切换 Key/Model），此过程会复用超时后延迟到达的 200 OK，并在尝试下一个 key 前检查它是否已完成。如果 3 个都超时，还有 5 秒的最终等待机会。单条消息整体处理设定 90 秒软上限（已在 2026-03-13 版本中优化为子任务独立计时）。
- **Key 尝试日志：** 每次 Key 切换均记录详细日志（第 X/3 次尝试），提升可观测性。

### **2025-12-08: Multi-Provider Support**
- **多服务商支持：** 新增 `providers.json` 配置文件，支持同时配置官方 Gemini API 和自定义中转 API。
- **配置迁移：** 废弃 `.env` 中的 `GEMINI_API_KEYS`，所有 API Key 统一管理在 `providers.json` 中。
- **自定义 Provider：** 支持添加任意兼容 Gemini 接口的自定义服务商（使用 Raw HTTP 请求）。
- **智能回退：** `providers.json` 中可配置多个服务商及优先级。当主服务商（如官方 API）不可用或速率受限时，自动切换至备用服务商，并发送 Webhook 通知。
- **精细化控制：** 支持为不同模型、不同服务商单独配置 RPM (Requests Per Minute) 速率限制。

## ⚙**安装与配置**

### 先手准备

[Discord bot token](https://discord.com/developers/applications)<br>[Gemini API key - Google AI studio](https://aistudio.google.com/)

### **环境要求**

- **Python 3.9+**

### **安装步骤**

- **克隆仓库**
    
    ```bash
    git clone https://github.com/zboomhaha/Walmart-Papago.git
    ```
    
- **安装依赖**
    
    ```bash
    cd Walmart-Papago
    pip install -r requirements.txt
    ```
    
- **修改.env，配置环境变量**
    
    ```plaintext
    #你的Discord bot token
    DISCORD_TOKEN=MAAAAAAA.GBBBBBBB.RCCCCCCCCCCCCCCCCCCCCCCCC-ng
          

    #接收错误通知的Webhook URL
    ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/000000000000/aaaaaaBBBBBBBBBBBcccccccDDDDDDR

    #接收错误通知的频道ID
    ERROR_CHANNEL_ID=0000000000000000000

    #默认语言，随便写，默认zh-CN
    DEFAULT_TARGET_LANG=zh-CN

    #日志等级配置
    #LOG_LEVEL_ROOT: 全局日志等级 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    #LOG_LEVEL_FILE: 文件日志等级
    #LOG_LEVEL_CONSOLE: 控制台日志等级
    
    LOG_LEVEL_ROOT=INFO
    LOG_LEVEL_FILE=INFO
    LOG_LEVEL_CONSOLE=INFO
    ```

- **配置 `providers.json`（新版核心配置）**
    
    机器人首次运行后会自动在根目录生成 `providers.json` 模板。你需要在此文件中配置 API Key 和服务商信息。

    **配置示例：**

    ```json
    {
        "settings": {
            "provider_order": ["official", "my_custom_provider"] // 服务商优先级顺序
        },
        "providers": {
            "official": {
                "type": "official", // 官方提供商类型
                "api_keys": [ "OFFICIAL_KEY_1", "OFFICIAL_KEY_2" ],
                "models": [ 
                    { "name": "gemini-2.5-flash", "rpm": 5 },
                    { "name": "gemini-2.5-flash-lite", "rpm": 10 }
                ]
            },
            "my_custom_provider": {
                "type": "custom", // 自定义提供商类型
                "base_url": "https://api.third-party.com", // 自定义 Base URL，结尾不可有斜杠
                "api_keys": [ "OFFICIAL_KEY_1", "OFFICIAL_KEY_2" ],
                "models": [
                    { "name": "gemini-2.5-flash", "rpm": 60 }, // 自定义 RPM
                    { "name": "gemini-2.5-flash-lite", "rpm": 60 } // 自定义 RPM
                ]
            }
        }
    }
    ```

    - **`type`**: `official` (官方SDK) 或 `custom` (第三方接口，必须支持Gemini原生格式)。
    - **`base_url`**: 自定义服务商的 API 地址（仅 `custom` 类型需要）。
    - **`rpm`**: 每分钟请求数限制（Per Key），机器人会根据此值对每个 Key 独立进行速率控制，多 Key 之间速率互不干扰。

    > ⚠️ **关于自定义 Provider 的重要提示：**
    > - `base_url` 必须指向支持 **Gemini 原生 API 格式**（`v1beta/models/{model}:generateContent`）的端点。
    > - **不支持** OpenAI 兼容格式（`/v1/chat/completions`）的端点。
    > - 部分中转站需要使用特定的路径后缀（如 `/gemini`）来区分 Gemini 格式端点，请参考中转站的使用文档确认正确的 Base URL。
    > - 示例：如果中转站地址是 `https://example.com/gemini`，则 `base_url` 应填写 `https://example.com/gemini`（结尾不可有斜杠）。

    
- **运行bot**
    
    ```jsx
    python3 discord_bot.py
    ```
    

- **升级已有bot**

    在停用bot之后，使用`pip install -r requirements.txt`重新安装依赖库后重启bot即可使用。

## 📔**使用指南**

### **Discord指令列表**

- `/set_translation_channel` ：设置当前频道为翻译源频道，可用参数`target_channel`选择另一个目标频道。
- `/remove_translation_channel`：移除当前频道的翻译功能。
- `/list_translation_channels`：列出所有翻译频道的映射关系。
- `/block_user`：阻止指定用户的消息被翻译。
- `/unblock_user`：解除对指定用户的翻译阻止。
- `/block_webhook`：阻止指定Webhook的消息被翻译（需要手动填入Webhook ID，请自行搜索如何获取该ID）。
- `/unblock_webhook`：解除对指定Webhook的翻译阻止（需要手动填入Webhook ID，请自行搜索如何获取该ID）。
- `/list_blocks`：列出所有被阻止翻译的用户、bot和Webhook。
- `/add_glossary_term`：添加自定义术语。（参数：`original`、`translation` ）
- `/remove_glossary_term`：移除自定义术语。
- `/list_glossary`：列出所有自定义术语。
- `/add_skip_keyword`：添加需要被跳过翻译的关键词。
- `/remove_skip_keyword`：移除需要被跳过翻译的关键词。
- `/list_skip_keywords`：列出所有需要被跳过翻译的关键词。

## ⚖**开源许可证**

本项目使用GNU General Public License v3.0进行许可，详细信息请参见[LICENSE](https://www.gnu.org/licenses/gpl-3.0.txt)。

## 🙏**致谢**

- [LINUX DO - 新的理想型社区](https://linux.do/)
- [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free)
- [Cursor-Chat-Exporter](https://github.com/Cranberrycrisp/Cursor-Chat-Exporter)
- [googleocr-app](https://github.com/cokice/googleocr-app)
- [GeminiTranslate](https://github.com/MUTED64/GeminiTranslate)

## 🌟**推荐配合以下Discord项目使用**

- [MonitoRSS](https://github.com/synzen/MonitoRSS)
- [Tweetcord](https://github.com/Yuuzi261/Tweetcord)
- [InstaWebhooks](https://github.com/RyanLua/InstaWebhooks)
- [weibo-discord-bot](https://github.com/Astralea/weibo-discord-bot)
- [worker-bilibili-discord](https://github.com/UnluckyNinja/worker-bilibili-discord)

