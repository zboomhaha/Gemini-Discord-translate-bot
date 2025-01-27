<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737963243834_walmart_papago_logo.png" width="200" height="200" /></div>
<div align="center">
<h1><strong>Walmart Papago Discord Translation Bot</strong></h1>
</div>
<br>

## 📄**Introduction**

Walmart Papago is a self-hosted, Gemini-powered Discord translation bot that can translate text, images, and embed messages in real-time within specified channels.<br>Adapted to Discord's features, it segments and returns the original text, translation, and annotations for easy copy-pasting.

## 💡**Key Features**

### **1. Slash Commands**

- **Set Translation Channel:** (A→A or A→B or A, B→C are all supported).
- **Glossary & skip keywords:** Manage related dictionaries directly using Slash Commands with hot-reloading configurations.
- **Block & unblock:** Supports blocking messages from specific users/bots/webhooks from being translated.

### **2. Content Handling**

- **Multi-Format Content Parsing:** Supports translation of `plain text`, `attached images`, `embeds`, `forwarded messages`. (When handling forwarded messages, the bot needs permission to read the source channel).
- **Content Pre-Filtering:** Filters out lines that only contain emojis, custom Discord emojis, punctuation, numbers, or empty content to reduce redundant translations.
- **Automatic URL Wrapping:** Automatically wraps URLs with ``` to prevent repeated recognition and expansion by bots who fix URL.

### **3. Optimized Load Balancing**

- **Dual-Model Auto-Switching:** Automatically switches to the backup model `gemini-1.5-flash` if the primary model `gemini-2.0-flash-exp` fails.
- **Smart Rate Limiting:** Randomly rotates multiple API keys, with built-in rate limiting and retry strategies to avoid 429 errors.
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
          
    # Gemini API key(s); filling at least one is sufficient
    GEMINI_API_KEYS=A0000000_V111111111111111,A0000000_V222222222222222,A0000000_V333333333333333....      

    # Webhook URL for receiving error notifications
    ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/000000000000/aaaaaaBBBBBBBBBBBcccccccDDDDDDR      

    # Channel ID for receiving error notifications
    ERROR_CHANNEL_ID=0000000000000000000      

    # User ID for receiving error notifications
    ERROR_NOTIFY_USER_ID=0000000000000000000      

    # Default language, can be anything, default is zh-CN
    DEFAULT_TARGET_LANG=zh-CN      
    ```
    
- **Run the Bot**
    
    ```bash
    python3 discord_bot.py
    ```
    

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
