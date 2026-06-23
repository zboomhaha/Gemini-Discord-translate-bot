<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737963243834_walmart_papago_logo.png" width="200" height="200" /></div>
<div align="center">
<h1><strong>Walmart Papago Discord Translation Bot</strong></h1>
</div>
<div align="center">
    <a href="https://github.com/zboomhaha/Walmart-Papago/blob/main/README.md">中文</a>
</div>
<br>
</div>
<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737972141929_ezgif-7-2bcd85fa0a55_1.gif" width="700" /></div>
<br>

## 📄**Introduction**

Walmart Papago is a self-hosted, Gemini-powered Discord translation bot that can translate text, images, and embed messages in real-time within specified channels.<br>Adapted to Discord's features, it segments and returns the original text, translation, and annotations for easy copy-pasting.

## 💡**Key Features**

### **1. Slash Commands**

- **Set Translation Channel:** (A→A or A→B or A, B→C are all supported).
- **Glossary & skip keywords:** Manage related dictionaries directly using Slash Commands with hot-reloading configurations.
- **Block & unblock:** Supports blocking messages from specific users/bots/webhooks from being translated.

### **2. Content Handling**

- **Multi-Format Content Parsing:** Supports translation of `plain text`, `attached images`, `embeds`, `forwarded messages`, `FxTwitter`. (When handling forwarded messages, the bot needs permission to read the source channel).
- **Content Pre-Filtering:** Filters out lines that only contain emojis, custom Discord emojis, punctuation, numbers, or empty content to reduce redundant translations.
- **Automatic URL Wrapping:** Automatically wraps URLs with ``` to prevent repeated recognition and expansion by bots who fix URL.

### **3. Optimized Load Balancing**

- **Three-Layer Fallback:** Key failure → Retry with random key (up to 3 attempts) → Model Cooldown → Switch to backup model → Provider Fallback to next provider.
- **Intelligent Error Classification:** 503 triggers a 5-minute model cooldown; 429 retries with a different key; 400/403 disables the key and sends a webhook alert with key details.
- **Per-Key RPM Limiting:** RPM limits are enforced per individual key, so multiple keys run at full capacity independently.
- **Granular Task-Level Timeouts:** Implemented an atomic timing strategy. Text translation (60s) and image translation (90s) are timed independently. Timing only covers the API interaction stage; asynchronous I/O like Discord message sending does not consume the translation quota.
- **Global 600s Fallback Protection:** A generous global timeout (10 mins) is used solely for deadlock recovery.
- **Adaptive Concurrency Control:** Built-in message deduplication and caching mechanisms, with an asynchronous message queue ensuring Discord messages are processed in the order they were sent.
- **Automatic Log Rotation & Cleanup:** Logs older than 7 days are automatically cleaned up, and log files are rotated daily to maintain system efficiency.

## 📅**Update Log**

### **2026-06-24: Custom Image Request Compatibility & Error Alerts**
- **Image request compatibility:** Custom API image requests now use the Gemini native REST field format (`inlineData` / `mimeType`), fixing cases where text requests worked but image requests returned permission errors on compatible endpoints.
- **Partial-success error alerts:** When a message is partially translated but an image sub-task or authentication-related critical sub-task fails, the bot now sends a throttled Webhook alert instead of only writing the failure to logs.
- **Error notification side-effect fix:** Sending an error notification no longer restarts the message queue. Queue recovery remains handled by the global task error handler.
- **Notification length protection:** Long error details are truncated before being sent to avoid Discord Embed description length limits.

### **2026-04-08: Custom Provider Robustness Refactor & Error Collection System**
- **Authentication Compatibility (Dual-Auth):** Implemented "dual-delivery" authentication (sending the API key in both URL parameters and `x-goog-api-key` headers) to resolve `401 Unauthorized` issues caused by proxy servers that do not forward URL parameters.
- **Strict Response Validation (Response Guardian):** Introduced strict detection for `text/html` responses. When an API returns a Cloudflare verification page or an HTML error, the bot extracts the HTML title and raises a clear error instead of failing silently with empty content.
- **Redirect & Internal Error Interception:** Added explicit detection for 3xx redirects and protection against APIs that return HTTP 200 with JSON structures containing `error` fields.
- **Error Collection System:** Refactored the management of translation sub-tasks. For multiple requests within a single message (Text, Embed, FxTwitter, multiple attachments), the bot now collects all exceptions. If one part fails (e.g., OCR error), translation of other parts continues. A comprehensive Webhook alert is sent only if all sub-tasks fail, reducing alert noise.
- **Startup Connection Self-Test (Health Check):** Added a connectivity test for all custom providers during startup. If failures occur due to improper Base URL configuration (e.g., using OpenAI format instead of Gemini format), clear warnings are provided in the logs.

### **2026-03-13: Prompt Instruction Refinement & Layout Logic Optimization**
- **In-depth Prompt Audit & Fixes:** Conducted a comprehensive review of `TRANSLATION_PROMPT` and `IMAGE_TRANSLATION_PROMPT`. Fixed instructional contradictions between "preserving original paragraph structure" and "line break handling," and resolved logical conflicts in the Notes section regarding "adding explanatory notes" versus "invoking glossary terms."
- **Redundant Instruction Cleanup:** Merged multiple repetitive rules concerning accuracy, readability, and Glossary mappings. Streamlined early-stage roleplay descriptions, reducing Token consumption while enhancing model adherence to instructions without sacrificing translation quality.
- **Image Context Verification:** Optimized source context identification instructions for image translation, enabling the model to more accurately match the tone and context of social media screenshots, articles, or chat logs.

### **2026-03-13: Independent Translation Task Timeouts & Stability Enhancement**
- **Task-Level Independent Timeouts:** Completely refactored the translation task timing logic by decoupling the timeouts for text translation (60s) and image translation (90s) within a single Discord message. Even if one message contains multiple text/image links (e.g., FxTwitter), each sub-task is timed independently, preventing unexpected interruptions caused by cumulative API latency.
- **Optimized Timing Metric:** Refined the endpoint for timeout calculations. Timing now only covers the duration until the model successfully returns a response (translation content or 200 OK). Expensive Discord message sending I/O is no longer counted against the translation timeout budget.
- **Global Deadlock Fuse:** Relaxed the global `handle_message` timeout to 10 minutes (600s). This limit now serves only as a last-resort safety mechanism against code loops or deadlocks, and normal translation workflows are no longer constrained by it.
- **Message Splitting Optimization:** Enhanced the message splitting logic for long text and notes to ensure smoother delivery to Discord when dealing with large model responses.

### **2025-03-05: Fallback Mechanism Refactor**
- **Intelligent Error Classification:** HTTP status codes now determine fallback behavior: 503 (model overloaded) immediately skips the model and enters a 5-minute cooldown; 429 (quota exhausted) retries with a randomly selected key; 400/403 (invalid key) automatically disables the key and sends a webhook alert to the admin.
- **Per-Key RPM Limiting:** RPM limits are now enforced per individual key, so multiple keys operate at full capacity independently without interfering with each other.
- **Random Key Selection:** Replaced fixed round-robin polling with random key selection to avoid hotspots.
- **Two-Layer Timeout Protection:** Each API call has a 10-20 second timeout (for fast key/model switching). This process reuses the 200 OK response even if it arrives after the timeout and checks if previous requests completed. If all 3 keys time out, there is still a 5-second final waiting opportunity. The overall processing per message had a 90s soft limit (now optimized into independent sub-task timers in the 2026-03-13 update).
- **Key Attempt Logging:** Each key switch is logged in detail (attempt X/3), improving observability.

### **2024-12-08: Multi-Provider Support**
- **Multi-Provider Architecture:** Added `providers.json` configuration to support both official Google Gemini API and custom third-party APIs simultaneously.
- **Config Migration:** Deprecated `GEMINI_API_KEYS` in `.env`. All API keys are now managed centrally in `providers.json`.
- **Custom Providers:** Support for any Gemini-compatible third-party provider via raw HTTP requests.
- **Smart Fallback:** Configure multiple providers with priority. If the primary provider (e.g., Official) fails or hits rate limits, the bot automatically switches to the backup provider and sends a webhook notification.
- **Granular Control:** Configure RPM (Requests Per Minute) limits individually for different models and providers.

## ⚙**Installation & Configuration**

### Prerequisites

[Discord Bot Token](https://discord.com/developers/applications)<br>[Gemini API Key - Google AI Studio](https://aistudio.google.com/)

### **Environment Requirements**

- **Python 3.9+**

### **Installation Steps**

- **Clone the Repository**
    
    ```bash
    git clone https://github.com/zboomhaha/Walmart-Papago.git
    ```
    
- **Install Dependencies**
    
    ```bash
    cd Walmart-Papago
    pip install -r requirements.txt
    ```
    
- **Edit the .env file to set up environment variables**
    
    ```plaintext
    # Your Discord bot token
    DISCORD_TOKEN=MAAAAAAA.GBBBBBBB.RCCCCCCCCCCCCCCCCCCCCCCCC-ng
          

    # Webhook URL for receiving error notifications
    ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/000000000000/aaaaaaBBBBBBBBBBBcccccccDDDDDDR

    # Channel ID for receiving error notifications
    ERROR_CHANNEL_ID=0000000000000000000

    # Default language, can be anything, default is zh-CN
    DEFAULT_TARGET_LANG=zh-CN

    # Logging Configuration
    # LOG_LEVEL_ROOT: Global logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    # LOG_LEVEL_FILE: File logging level
    # LOG_LEVEL_CONSOLE: Console logging level    
    LOG_LEVEL_ROOT=INFO
    LOG_LEVEL_FILE=INFO
    LOG_LEVEL_CONSOLE=INFO
    ```

- **Configure `providers.json` (New Core Configuration)**
    
    The bot will automatically generate a `providers.json` template in the root directory upon first run. You need to configure your API keys and provider information here.

    **Configuration Example:**

    ```json
    {
        "settings": {
            "provider_order": ["official", "my_custom_provider"] // Priority order
        },
        "providers": {
            "official": {
                "type": "official", // Official Google SDK
                "api_keys": [ "OFFICIAL_KEY_1", "OFFICIAL_KEY_2" ],
                "models": [ 
                    { "name": "gemini-2.5-flash", "rpm": 5 },
                    { "name": "gemini-2.5-flash-lite", "rpm": 10 }
                ]
            },
            "my_custom_provider": {
                "type": "custom", // Custom HTTP Provider
                "base_url": "https://api.third-party.com", // Custom Base URL, no slash in the end
                "api_keys": [ "CUSTOM_KEY_1" ],
                "models": [
                    { "name": "gemini-2.5-flash", "rpm": 60 } // Custom RPM
                ]
            }
        }
    }
    ```

    - **`type`**: `official` (SDK) or `custom` (For custom providers. Must support the Gemini native format).
    - **`base_url`**: API endpoint for custom providers (required for `custom` type).
    - **`rpm`**: Requests Per Minute limit (Per Key). The bot enforces rate limiting independently for each key, so multiple keys do not interfere with each other's quota.

    > ⚠️ **Important Notes for Custom Providers:**
    > - `base_url` must point to an endpoint that supports the **Gemini native API format** (`v1beta/models/{model}:generateContent`).
    > - OpenAI-compatible endpoints (`/v1/chat/completions`) are **not supported**.
    > - Some third-party providers require a specific path suffix (e.g., `/gemini`) to access the Gemini API endpoint. Please refer to your provider's documentation to confirm the correct Base URL.
    > - Example: If the provider's address is `https://example.com/gemini`, set `base_url` to `https://example.com/gemini` (no trailing slash).

    
- **Run the Bot**
    
    ```bash
    python3 discord_bot.py
    ```
    

- **Upgrading an existing bot**

    After stopping the bot, reinstall the dependencies using `pip install -r requirements.txt` and then restart the bot.

## 📔**How To Use**

### **Discord Command List**

- `/set_translation_channel`: Set the current channel as the source translation channel, with the option to specify a target channel using the `target_channel` parameter.
- `/remove_translation_channel`: Stop translating messages in current channel.
- `/list_translation_channels`: List all translation channel mappings.
- `/block_user`: Block messages from a specific user from being translated.
- `/unblock_user`: Unblock messages from a specific user from being translated.
- `/block_webhook`: Block messages from a specific webhook from being translated (requires manually entering the webhook ID; search for how to obtain it).
- `/unblock_webhook`: Unblock messages from a specific webhook (requires manually entering the webhook ID; search for how to obtain it).
- `/list_blocks`: List all blocked users, bots, and webhooks.
- `/add_glossary_term`: Add a glossary term. (Parameters: `original`, `translation`)
- `/remove_glossary_term`: Remove a glossary term.
- `/list_glossary`: List all glossary terms.
- `/add_skip_keyword`: Add a keyword to be skipped during translation.
- `/remove_skip_keyword`: Remove a keyword from the skip list.
- `/list_skip_keywords`: List all keywords to be skipped during translation.

## ⚖**License**

This project is licensed under the GNU General Public License v3.0. For full licensing terms, see [LICENSE](https://www.gnu.org/licenses/gpl-3.0.txt).

## 🙏**Credits**

- [LINUX DO - A New Ideal Community](https://linux.do/)
- [cursor-auto-free](https://github.com/chengazhen/cursor-auto-free)
- [Cursor-Chat-Exporter](https://github.com/Cranberrycrisp/Cursor-Chat-Exporter)
- [googleocr-app](https://github.com/cokice/googleocr-app)
- [GeminiTranslate](https://github.com/MUTED64/GeminiTranslate)

## 🌟**Recommended Discord Projects to Use Alongside**

- [MonitoRSS](https://github.com/synzen/MonitoRSS)
- [Tweetcord](https://github.com/Yuuzi261/Tweetcord)
- [InstaWebhooks](https://github.com/RyanLua/InstaWebhooks)
- [weibo-discord-bot](https://github.com/Astralea/weibo-discord-bot)
- [worker-bilibili-discord](https://github.com/UnluckyNinja/worker-bilibili-discord)
