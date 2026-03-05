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

## 📅**Update Log**

### **2025-03-05: Fallback Mechanism Refactor**
- **Intelligent Error Classification:** HTTP status codes now determine fallback behavior: 503 (model overloaded) immediately skips the model and enters a 5-minute cooldown; 429 (quota exhausted) retries with a randomly selected key; 400/403 (invalid key) automatically disables the key and sends a webhook alert to the admin.
- **Per-Key RPM Limiting:** RPM limits are now enforced per individual key, so multiple keys operate at full capacity independently without interfering with each other.
- **Random Key Selection:** Replaced fixed round-robin polling with random key selection to avoid hotspots.
- **Two-Layer Timeout Protection:** Each API call has a 10-second timeout (for fast key/model switching), this process will reuse the 200 OK response after timeout and check if the previous key's request has completed; if the previous key's request has already returned 200 OK, it will use it directly. If all 3 keys time out, there is still a 5-second final waiting opportunity. Each message has an overall 90-second processing timeout (to prevent queue blocking). On timeout, an error webhook is sent, and DM users receive a "Service busy, please try again later" reply.
- **Key Attempt Logging:** Each key switch is logged in detail (attempt X/3), improving observability.

### **2024-12-08: Multi-Provider Support**
- **Multi-Provider Architecture:** Added `providers.json` configuration to support both official Google Gemini API and custom third-party APIs simultaneously.
- **Config Migration:** Deprecated `GEMINI_API_KEYS` in `.env`. All API keys are now managed centrally in `providers.json`.
- **Custom Providers:** Support for any Gemini-compatible third-party provider via raw HTTP requests.
- **Smart Fallback:** Configure multiple providers with priority. If the primary provider (e.g., Official) fails or hits rate limits, the bot automatically switches to the backup provider and sends a webhook notification.
- **Granular Control:** Configure RPM (Requests Per Minute) limits individually for different models and providers.

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
- **Two-Layer Timeout Protection:** 10-second per-call timeout for fast failover; 90-second per-message timeout to prevent queue blocking. Admins are notified on timeout, and DM users receive a busy reply.
- **Adaptive Concurrency Control:** Built-in message deduplication and caching mechanisms, with an asynchronous message queue ensuring Discord messages are processed in the order they were sent.
- **Automatic Log Rotation & Cleanup:** Logs older than 7 days are automatically cleaned up, and log files are rotated daily to maintain system efficiency.

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
