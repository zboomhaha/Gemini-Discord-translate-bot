<div align=center><img src="https://newjeansr-imgbed.pages.dev/file/1737963243834_walmart_papago_logo.png" width="200" height="200" /></div>
<div align="center">
<h1><strong>Walmart Papago Discord translation bot</strong></h1>
</div>
<div align="center">
    <a href="https://github.com/zboomhaha/Walmart-Papago/blob/main/README-EN.md">English</a>
</div>
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

- **多格式内容解析：** 支持`普通文本`、`附件图片`、`Embed` 、`引用消息`等多种内容格式的翻译。（处理引用消息时，bot需要拥有读取该消息源频道的权限）
- **内容预过滤：** 预过滤仅包含Emoji/Discord自定义表情/中英标点符号/纯数字/空内容的自然行，避免输出多余的翻译内容。
- **自动包裹URL：** 自动识别并使用```包裹URL，避免FIX-URL类的Discord Bot重复识别URL并展开URL内容。

### **3. 负载均衡优化**

- **双模型自动切换：** 主模型`gemini-2.0-flash-exp`失败时自动切换到备用模型`gemini-1.5-flash`。
- **智能速率限制：** 随机轮换多个API 密钥、内置请求速率限制与重试策略，避免429。
- **自适应并发控制：** 内置消息去重与缓存机制，异步消息队列可确保频道内的Discord消息按发送顺序处理。
- **自动轮转和清理日志：** 日志文件每日自动轮转，自动清理超过7天的日志记录。

### **4. Default Language=zh-CN的彩蛋**

- **中文小标题：** 翻译反馈中的小标题将以简体中文来显示，否则默认显示英文。（如：“文字翻译”&“Text Translation”）
- **智能跳过中文行：** 如果单行中的中文占比超过50%，则该行不会被提交至Gemini进行翻译。

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
          
    #Gemini API key,可以只填一个
    GEMINI_API_KEYS=A0000000_V111111111111111,A0000000_V222222222222222,A0000000_V333333333333333....      

    #接收错误通知的Webhook URL
    ERROR_WEBHOOK_URL=https://discord.com/api/webhooks/000000000000/aaaaaaBBBBBBBBBBBcccccccDDDDDDR      

    #接收错误通知的频道ID
    ERROR_CHANNEL_ID=0000000000000000000      

    #接收错误通知的用户ID
    ERROR_NOTIFY_USER_ID=0000000000000000000      

    #默认语言，随便写，默认zh-CN
    DEFAULT_TARGET_LANG=zh-CN      
    ```
    
- **运行bot**
    
    ```jsx
    python3 discord_bot.py
    ```
    

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

