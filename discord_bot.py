import asyncio
import logging
import re
import aiohttp
import json
import io
import time
import signal
import sys
import os
import emoji
import functools
import discord
from discord import app_commands, Interaction
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime
from typing import Optional
from translator import Translator
from config import (
    Config, DISCORD_TOKEN, ERROR_WEBHOOK_URL, ERROR_CHANNEL_ID, EMPTY_INDICATORS,
    LOG_LEVEL_ROOT, LOG_LEVEL_FILE, LOG_LEVEL_CONSOLE
)
from logging.handlers import TimedRotatingFileHandler



load_dotenv()

class TranslatorBot(commands.Bot):



    """ INITIALIZATION """

    def __init__(self):
        
        # setup logging
        self.setup_logging()
        
        # Initialize Discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True  # Enable DM messages
        intents.members = True  # Enable members intent for fetching guild members
        super().__init__(
            command_prefix="!",
            intents=intents,
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="Papago"
            )
        )
        
        # Initialize ready event
        self._ready = asyncio.Event()

        # Add configuration
        self.config = Config()  # Use singleton configuration     

        # initialize session
        self.session = None 

        # Initialize message queue and lock
        self.message_queue = None  
        self.processing_lock = None  

        # Initialize message cache configuration
        self._message_cache = {}
        self.message_ttl = 3600  # 1 hour expiration
        self._cache_cleanup_interval = 600  # clean cache every 10 minutes
        self._max_cache_size = 100  # maximum cache size

        # Initialize message processing task
        self.message_processor_task = None

        # Initialize cleanup task  
        self.cleanup_task = None

        # Initialize error handling configuration
        self.MAX_RETRY_ATTEMPTS = 3  # maximum retry attempts
        self.RETRY_DELAY = 5  # retry interval (seconds)
        self._keep_running = True

        # Initialize translator 
        self.translator = Translator() 
        self.translation_channels = self.load_translation_channels()
          
        # Add blocked users file path
        self.blocked_users_file = 'blocked_users.json'
        self.blocked_users = self.load_blocked_users()

        # Add DM whitelist file path and initialization
        self.dm_whitelist_file = 'dm_whitelist.json'
        self.dm_whitelist = self.load_dm_whitelist()
        self.whitelist_update_task = None
        
        # Add regex patterns as class properties
        self.discord_emoji_pattern = r'<a?:\w+:\d+>'  # Discord custom emojis
        self.url_pattern = r'https?://[^\s<>[\]]+[^\s.,<>[\]]'  # URLs
        
        # Add character range constants
        self.CHAR_RANGES = {
            'chinese': r'[\u4e00-\u9fff]',
            'japanese': r'[\u3040-\u309F\u30A0-\u30FF]',
            'korean': r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]'
        }      
        # Add signal handler
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

        # Finish initialization notification
        self.logger.info("Bot initialized") 

    def setup_logging(self):
        """Setup logging"""
        # create log directory
        self.log_dir = 'logs'
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        
        # setup logging format and get root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(LOG_LEVEL_ROOT)
        
        # Clear all existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # setup daily rotating file handler for INFO level
        log_file = os.path.join(self.log_dir, 'walmart_papago.log')
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=7,  # keep 7 days of logs
            encoding='utf-8'
        )
        file_handler.setLevel(LOG_LEVEL_FILE)  # Ensure file handler uses INFO level
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        root_logger.addHandler(file_handler)
        
        # Setup console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(LOG_LEVEL_CONSOLE)  # Show debug level in console
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        root_logger.addHandler(console_handler)
        
        # Initialize bot's logger
        self.logger = logging.getLogger(__name__)
        
    async def setup_hook(self):

        try:
            # Initialize message queue and lock    
            self.message_queue = asyncio.Queue()
            self.processing_lock = asyncio.Lock()
            
            # Initialize Discord Bot's independent session
            self.session = aiohttp.ClientSession()

            # Start cleanup tasks
            self.cleanup_task = self.loop.create_task(self._cleanup_messages())

            # Start DM whitelist update task
            self.whitelist_update_task = self.loop.create_task(self._update_dm_whitelist())

            self.logger.info("Initialized setup hook.")           
            
            # Register all commands (guild-only to prevent showing in DMs)
            commands_info = [
                ("set_translation_channel", "Set current channel as translation channel", self.set_translation_channel),
                ("remove_translation_channel", "Remove translation feature from current channel", self.remove_translation_channel),
                ("list_translation_channels", "List all translation channel mappings", self.list_translation_channels),
                ("block_user", "Block message translation for specified user/bot", self.block_user),
                ("unblock_user", "Unblock message translation for specified user/bot", self.unblock_user),
                ("block_webhook", "Block webhook", self.block_webhook),
                ("unblock_webhook", "Unblock webhook", self.unblock_webhook),
                ("list_blocks", "List all blocked users/bots/webhooks", self.list_blocks),
                ("add_glossary_term", "Add glossary term", self.add_glossary_term),
                ("remove_glossary_term", "Remove glossary term", self.remove_glossary_term),
                ("list_glossary", "List all glossary terms", self.list_glossary),
                ("add_skip_keyword", "Add a skip keyword", self.add_skip_keyword),
                ("remove_skip_keyword", "Remove a skip keyword", self.remove_skip_keyword),
                ("list_skip_keywords", "List all skip keywords", self.list_skip_keywords),
            ]

            for name, description, callback in commands_info:
                cmd = app_commands.Command(
                    name=name,
                    description=description,
                    callback=callback
                )
                # Mark command as guild-only to prevent showing in DMs
                cmd.guild_only = True
                self.tree.add_command(cmd)

            await self.tree.sync(guild=None) 
            self.logger.info("All commands registered and synced.")
            
            # Start message processing task
            if self.message_processor_task is None:
                self.message_processor_task = self.loop.create_task(self.process_message_queue())
                self.message_processor_task.add_done_callback(
                    lambda t: asyncio.create_task(self.handle_queue_processor_error(t))
                )
                self.logger.info("Message processing task started")
            
            # Connect info
            self._ready.set()
            self.logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
            
            # Finish setup notification
            self.logger.info("Bot setup completed.")

        except Exception as e:
            self.logger.error(f"Failed to setup bot: {str(e)}", exc_info=True)
            async with aiohttp.ClientSession() as temp_session:
                webhook = discord.Webhook.from_url(ERROR_WEBHOOK_URL, session=temp_session)
                await webhook.send(f"Setup Error: {str(e)}")
            await asyncio.sleep(10) 
            await self.close()
                    
    async def on_connect(self):
        self.logger.info("Bot connected to Discord")
        self.logger.info(f"Latency: {round(self.latency * 1000)}ms")

        # Trigger immediate whitelist update after connection
        if hasattr(self, '_first_connect') and self._first_connect:
            return
        self._first_connect = True

        # Wait a bit for guilds to be populated after connection
        await asyncio.sleep(2)
        self.logger.debug(f"After connection, guilds count: {len(self.guilds)}")

        # Manually trigger whitelist update
        asyncio.create_task(self._do_whitelist_update())

    async def on_disconnect(self):
        self.logger.info("Bot disconnected from Discord")    

    def load_translation_channels(self):
        """Load translation channel mappings from file"""
        try:
            with open('translation_channels.json', 'r') as f:
                data = json.load(f)
                # If it's an old list format, convert to new dictionary format
                if isinstance(data, list):
                    return {channel_id: channel_id for channel_id in data}
                # If it's a new dictionary format
                return {int(k): int(v) for k, v in data.items()}
        except FileNotFoundError:
            # Create default empty dictionary
            default_data = {}
            with open('translation_channels.json', 'w') as f:
                json.dump(default_data, f)
            return default_data
        except Exception as e:
            self.logger.error(f"Failed to load translation channels: {str(e)}")
            return {}    

    def load_blocked_users(self):
        """Load blocked list from file"""
        try:
            if os.path.exists(self.blocked_users_file):
                with open(self.blocked_users_file, 'r') as f:
                    return json.load(f)
            # If file doesn't exist, create default empty list
            default_data = []
            with open(self.blocked_users_file, 'w') as f:
                json.dump(default_data, f)
            return default_data
        except Exception as e:
            self.logger.error(f"Failed to load blocked users: {str(e)}")
            return []  # Return empty list if error

    def load_dm_whitelist(self):
        """Load DM whitelist from file"""
        try:
            if os.path.exists(self.dm_whitelist_file):
                with open(self.dm_whitelist_file, 'r') as f:
                    data = json.load(f)
                    # Convert to set for faster lookup, ensure all are strings
                    return set(str(uid) for uid in data.get('auto_users', []))
            # If file doesn't exist, create default empty structure
            default_data = {'auto_users': []}
            with open(self.dm_whitelist_file, 'w') as f:
                json.dump(default_data, f, indent=2)
            return set()
        except Exception as e:
            self.logger.error(f"Failed to load DM whitelist: {str(e)}")
            return set()

    def save_dm_whitelist(self):
        """Save DM whitelist to file"""
        try:
            data = {'auto_users': sorted(list(self.dm_whitelist))}
            with open(self.dm_whitelist_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"Saved DM whitelist with {len(self.dm_whitelist)} users")
        except Exception as e:
            self.logger.error(f"Failed to save DM whitelist: {str(e)}")

    def require_permissions(permission):
        """Decorator for permission checking"""
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
                # Check if used in server
                if not interaction.guild:
                    await interaction.response.send_message("This command can only be used in a server", ephemeral=True)
                    return
                
                # Get user info - try multiple ways to get member info
                member = interaction.user
                if not isinstance(member, discord.Member):
                    # Try to get from cache
                    member = interaction.guild.get_member(interaction.user.id)
                    if not member:
                        try:
                            # If not in cache, fetch from API
                            member = await interaction.guild.fetch_member(interaction.user.id)
                        except discord.NotFound:
                            await interaction.response.send_message("Failed to get user info, please ensure you are in the server", ephemeral=True)
                            return
                        except discord.HTTPException as e:
                            await interaction.response.send_message(f"Failed to get user info: {str(e)}", ephemeral=True)
                            return
                
                # Permission check
                has_permission = False
                error_message = ""
                
                if permission == 'administrator':
                    has_permission = member.guild_permissions.administrator
                    error_message = "This command requires administrator permissions"
                elif permission == 'manage_messages':
                    has_permission = member.guild_permissions.manage_messages or member.guild_permissions.administrator
                    error_message = "This command requires manage messages permissions"
                elif permission == 'manage_webhooks':
                    has_permission = member.guild_permissions.manage_webhooks or member.guild_permissions.administrator
                    error_message = "This command requires manage webhooks permissions"
                else:
                    error_message = f"Unknown permission requirement: {permission}"
                
                if not has_permission:
                    await interaction.response.send_message(error_message, ephemeral=True)
                    return
                    
                return await func(self, interaction, *args, **kwargs)
                
            wrapper.__discord_app_commands_param_annotations__ = getattr(
                func, '__discord_app_commands_param_annotations__', {}
            )
            wrapper.__discord_app_commands_param_defaults__ = getattr(
                func, '__discord_app_commands_param_defaults__', {}
            )
            return wrapper
        return decorator



    """ MESSAGE PROCESSING """

    #Listening message and pre-check
    async def on_message(self, message):
        """Message reception processing"""
        try:
            # Check 1: Whether it is a message from the bot itself
            if message.author == self.user:
                return

            # Check if it's a DM
            is_dm = isinstance(message.channel, discord.DMChannel)

            if is_dm:
                # For DM: Check if user is in the whitelist
                if message.author.bot:
                    self.logger.debug(f"Ignoring DM from bot: {message.author}")
                    return

                # Check if user ID is in DM whitelist
                user_id_str = str(message.author.id)
                if user_id_str not in self.dm_whitelist:
                    self.logger.info(f"DM from user not in whitelist: {message.author} (ID: {user_id_str})")
                    try:
                        await message.channel.send("检测到你不在服务器中，暂时无法使用~")
                    except Exception as e:
                        self.logger.error(f"Failed to send rejection message: {str(e)}")
                    return

                self.logger.info(f"Processing DM from {message.author} (ID: {user_id_str})")
            else:
                # Check 2: For server messages, check if channel is in translation channels
                if message.channel.id not in self.translation_channels:
                    return
                
            # Check 3: Whether it has been processed
            message_key = f"{message.channel.id}:{message.id}"
            if message_key in self._message_cache:
                return

            # Check 4: Webhook blocking check
            if message.webhook_id:
                is_blocked = any(
                    str(block["id"]) == str(message.webhook_id) and block["type"] == "webhook"
                    for block in self.blocked_users
                )
                if is_blocked:
                    self.logger.info(f"Skipping message from blocked webhook: {message.webhook_id}")
                    return

            # Check 5: user/bot blocking check
            else:
                is_blocked = any(
                    block["id"] == message.author.id and block["type"] in ["user", "bot"]
                    for block in self.blocked_users
                )
                if is_blocked:
                    self.logger.info(f"Skipping message from blocked user: {message.author}")
                    return
                    
            # After passing all checks, add to queue
            await self.message_queue.put(message)
            if is_dm:
                self.logger.info(f"DM message {message.id} from {message.author} added to queue")
            else:
                self.logger.info(f"Message {message.id} added to queue from channel {message.channel.name}")
                
        except Exception as e:
            self.logger.error(f"Error in message pre-check: {str(e)}", exc_info=True)

    async def process_message_queue(self):
        """Process message queue"""
        await self._ready.wait() 
        retry_count = 0
        MAX_RETRIES = 3

        while self._keep_running:  
            try:
                message = await self.message_queue.get()
                async with self.processing_lock:
                    await self.handle_message(message)
                    await asyncio.sleep(self.config.TRANSLATION_COOLDOWN)
                    retry_count = 0  # Reset retry count after successful processing
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error processing message queue (attempt {retry_count}/{MAX_RETRIES}): {str(e)}", exc_info=True)
                if retry_count >= MAX_RETRIES:
                    self.logger.error("Reached maximum retry count, skipping current message")
                    retry_count = 0  # Reset retry count, continue processing next message
                    continue
                self.logger.info(f"Retrying {retry_count} times...")
                await asyncio.sleep(1)

    async def handle_message(self, message):
        """Message overall processing control and status recording"""
        self.logger.info(f"Start processing message: {message.id}")
        message_processed = False
        is_successful_run = False

        try:
            # Check if it's a DM
            is_dm = isinstance(message.channel, discord.DMChannel)

            if is_dm:
                # For DM, target channel is the DM channel itself
                target_channel = message.channel
                self.logger.info(f"Processing DM - will reply in same DM channel")
            else:
                # For server messages, use configured target channel
                target_channel_id = self.translation_channels.get(message.channel.id)
                if not target_channel_id:
                    self.logger.error(f"No target channel ID configured for: {message.channel.id}")
                    return False

                target_channel = self.get_channel(target_channel_id)
                if not target_channel:
                    self.logger.error(f"Target channel not found: {target_channel_id}")
                    return False

            # Record message processing
            message_key = f"{message.channel.id}:{message.id}"
            self._message_cache[message_key] = time.time()
            
            # Process referenced message
            referenced_message = await self.fetch_referenced_message(message)
            if referenced_message:
                ref_processed = await self.process_translated_content(referenced_message, target_channel)
                message_processed = message_processed or ref_processed
            
            # Process current message
            current_processed = await self.process_translated_content(message, target_channel)
            message_processed = message_processed or current_processed
            
            is_successful_run = message_processed
            if is_successful_run:
                self.logger.info("Message processing completed")
            return message_processed
        
        except Exception as e:
            if is_dm:
                self.logger.error(f"Error processing DM from {message.author}: {str(e)}", exc_info=True)
            else:
                self.logger.error(f"Error processing message: {str(e)}", exc_info=True)
            await self.send_error_message(str(e))
            return False
        
        finally:
            # Output corresponding logs based on processing status
            if not is_successful_run:
                status = "failed"
            elif message_processed:
                status = "successfully"
            else:
                status = "done"
            self.logger.info(f"Message {message.id} processed {status}")
            self.logger.info(f"End processing message: {message.id}")

    async def process_translated_content(self, message, target_channel):
        """Process specific message content, request translation and retrieve translation result"""
        success = False

        # Process normal text content
        if message.content:
            # Priority 1: Handle FxTwitter links
            fxtwitter_pattern = r'https?://fxtwitter\.com/\S+'
            fxtwitter_match = re.search(fxtwitter_pattern, message.content)
            
            if fxtwitter_match:
                url = fxtwitter_match.group(0)
                self.logger.info(f"Detected FxTwitter link: {url}")
                
                try:
                    # Handle the link
                    fxtwitter_processed = await self.handle_fxtwitter_link(url, target_channel)
                    success = success or fxtwitter_processed
                    
                    # If FxTwitter link was processed, skip the rest of the text content
                    if fxtwitter_processed:
                        self.logger.info("FxTwitter link processed successfully, skipping further text processing.")
                        return success # Return the current success status

                except Exception as e:
                    self.logger.error(f"Error handling FxTwitter link {url}: {e}", exc_info=True)
                    # If the handler fails, we should not proceed to process the rest of the message
                    # as if it were normal text, because it might misinterpret the content.
                    return False # Indicate failure and stop processing this message content.

            # Priority 2: Process remaining text content after special handling
            self.logger.info(f"Processing normal text content: {message.content[:100]}...")
            processed_text = self.text_pre_check(message.content)
            if processed_text:
                result = await self.translator.translate_text(processed_text)
                if isinstance(result, dict):
                    await self.send_translation_result(
                        target_channel,
                        result.get("original"),
                        result.get("translation"),
                        notes=result.get("notes")
                    )
                else:
                    await self.send_translation_result(target_channel, processed_text, result)
                success = True

        # Process attachments
        if message.attachments:
            await self.handle_attachments(message.attachments, target_channel)
            success = True

        # Process embeds
        for embed in message.embeds:
            embed_success = False

            if embed.title:
                processed_title = self.text_pre_check(embed.title)
                if processed_title:
                    try:
                        result = await self.translator.translate_text(processed_title)
                        if isinstance(result, dict):
                            await self.send_translation_result(
                                target_channel,
                                result.get("original"),
                                result.get("translation"),
                                notes=result.get("notes")
                            )
                        else:
                            await self.send_translation_result(target_channel, processed_title, result)
                        self.logger.info("Embed title translation completed")
                        embed_success = True
                    except Exception as e:
                        self.logger.error(f"Error translating embed title: {str(e)}", exc_info=True)

            if embed.description:
                processed_desc = self.text_pre_check(embed.description)
                if processed_desc:
                    try:
                        result = await self.translator.translate_text(processed_desc)
                        if isinstance(result, dict):
                            await self.send_translation_result(
                                target_channel,
                                result.get("original"),
                                result.get("translation"),
                                notes=result.get("notes")
                            )
                        else:
                            await self.send_translation_result(target_channel, processed_desc, result)
                        self.logger.info("Embed description translation completed")
                        embed_success = True
                    except Exception as e:
                        self.logger.error(f"Error translating embed description: {str(e)}", exc_info=True)

            if embed.image:
                self.logger.info(f"Processing embed image: {embed.image.url}")
                try:
                    translated_image = await self.translator.translate_image(embed.image.url)
                    if translated_image:
                        await self.send_translation_result(
                            target_channel,
                            translated_image.get("original"),
                            translated_image.get("translation"),
                            notes=translated_image.get("notes"),
                            image_url=embed.image.url
                        )
                        self.logger.info("Embed image translation completed")
                        embed_success = True
                except Exception as e:
                    self.logger.error(f"Error processing embed image: {str(e)}", exc_info=True)

            success = success or embed_success  # If any embed processing is successful, overall processing is successful

        return success  # Return processing status

    async def handle_fxtwitter_link(self, url, target_channel):
        """Handle FxTwitter link by fetching JSON data from the api.fxtwitter.com endpoint."""
        api_url = url.replace("fxtwitter.com", "api.fxtwitter.com")
        self.logger.info(f"Requesting FxTwitter API: {api_url}")

        try:
            async with self.session.get(api_url) as response:
                response.raise_for_status()  # Raise an exception for bad status codes
                data = await response.json()
                self.logger.debug(f"FxTwitter API response JSON: {json.dumps(data, indent=2)}")
                self.logger.info("Successfully parsed JSON from FxTwitter API.")

                tweet = data.get('tweet', {})
                description = tweet.get('text')
                media = tweet.get('media', {})
                image_urls = []

                # 1. Mixed media (videos first)
                if media.get('videos'):
                    for video in media['videos']:
                        if video.get('thumbnail_url'):
                            image_urls.append(video['thumbnail_url'])
                # 2. Mosaic (multiple images)
                elif media.get('mosaic') and media['mosaic'].get('formats', {}).get('jpeg'):
                    image_urls.append(media['mosaic']['formats']['jpeg'])
                # 3. Single photo
                elif media.get('photos'):
                    for photo in media['photos']:
                        if photo.get('url'):
                            image_urls.append(photo['url'])
                # 4. External video link
                elif media.get('external'):
                    image_urls.append(media['external'].get('thumbnail_url'))
                
                # Filter out any None values from image_urls
                image_urls = [url for url in image_urls if url]

                success = False
                if description:
                    processed_desc = self.text_pre_check(description)
                    if processed_desc:
                        result = await self.translator.translate_text(processed_desc)
                        if isinstance(result, dict):
                            await self.send_translation_result(
                                target_channel,
                                result.get("original"),
                                result.get("translation"),
                                notes=result.get("notes")
                            )
                        else:
                            await self.send_translation_result(target_channel, processed_desc, result)
                        success = True
                
                for image_url in image_urls:
                    self.logger.info(f"Processing image from FxTwitter: {image_url}")
                    translated_image = await self.translator.translate_image(image_url)
                    if translated_image:
                        await self.send_translation_result(
                            target_channel,
                            translated_image.get("original"),
                            translated_image.get("translation"),
                            notes=translated_image.get("notes"),
                            image_url=image_url
                        )
                        success = True
                
                return success

        except aiohttp.ClientError as e:
            self.logger.error(f"Network error fetching FxTwitter API {api_url}: {e}", exc_info=True)
            return False
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse JSON from FxTwitter API {api_url}: {e}", exc_info=True)
            return False
        except KeyError as e:
            self.logger.error(f"Key error when parsing FxTwitter JSON from {api_url}: Missing key {e}", exc_info=True)
            return False
        except Exception as e:
            self.logger.error(f"An unexpected error occurred while handling FxTwitter link {url}: {e}", exc_info=True)
            return False

    def text_pre_check(self, text: str) -> Optional[str]:
        """Process text content, return processed text or None"""
        try:
            if not text or not text.strip():
                return None
                
            # Split text by lines
            lines = text.split('\n')
            valid_lines = []
                
            for line in lines:
                # Skip empty lines
                if not line.strip():
                    continue
                
                # 0. Clean FxTwitter social proof
                                    
                # 1. Check if line contains keywords to be skipped
                should_skip = False
                line_lower = line.lower()
                for keyword in self.translator.skip_keywords:
                    if keyword.lower() in line_lower:  # Case-insensitive matching
                        self.logger.info(f"Skip keyword detected: {keyword}")
                        should_skip = True
                        break
                    
                if should_skip:
                    continue
                    
                # 2. Check if text contains only special content
                stripped_line = line.strip()
                is_special = self.contains_only_special_characters(stripped_line)
                self.logger.debug(f"Processing line: '{stripped_line}' | Is special only: {is_special}")
                if is_special:
                    self.logger.info(f"Skipping special content only line: '{stripped_line}'")
                    continue
                    
                # 3. Only perform should_skip_chinese check when target language is Simplified Chinese
                if self.config.DEFAULT_TARGET_LANG == "zh-CN" and self.should_skip_chinese(line):
                    continue
                    
                # 4. Process URLs
                processed_line = re.sub(
                    self.url_pattern,
                    lambda m: f'`{m.group(0)}`',
                    line
                )

                # 5. If processed line is not empty, add to valid lines list
                if processed_line.strip():
                    valid_lines.append(processed_line)
                    
            # If no valid lines, return None
            if not valid_lines:
                return None
                    
            # Combine valid lines back into text    
            return '\n'.join(valid_lines)
                    
        except Exception as e:
            self.logger.error(f"Error processing text: {str(e)}")
            return None

    def _get_channel_name(self, channel):
        """Get channel display name, handling both DM and regular channels"""
        if isinstance(channel, discord.DMChannel):
            return f"DM with {channel.recipient.name if channel.recipient else 'Unknown'}"
        return channel.name if hasattr(channel, 'name') else str(channel.id)

    async def send_translation_result(self, channel, original, translated, notes=None, image_url=None):
        """Format and send translation result to Discord"""
        try:
            channel_name = self._get_channel_name(channel)
            self.logger.info(f"Processing translation for sending to {channel_name}")
            messages = []

            # Set split titles based on target language
            titles = {
                "image_content": "> **图片内容：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Image Content:**",
                "image_text": "> **图片文字：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Image Text:**",
                "image_translation": "> **图片翻译：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Image Translation:**",
                "original_content": "> **原文内容：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Original Content:**",
                "text_translation": "> **文字翻译：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Text Translation:**",
                "notes": "> **注释：**" if self.config.DEFAULT_TARGET_LANG == "zh-CN" else "> **Notes:**"
            }

            if image_url:
                self.logger.info("Sending translated image")
                # Download image
                async with self.session.get(image_url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Failed to download image: HTTP {resp.status}")
                    data = io.BytesIO(await resp.read())
                # Create file object
                file = discord.File(data, filename="translated_image.png")
                messages.append({"content": titles["image_content"], "file": file})

                # Use different message format for image translation to avoid being treated as normal text
                if not original.startswith(("Notes: ")):
                    messages.append({"content": titles["image_text"]})
                    if original:  # Ensure original is not empty
                        messages.append({"content": f"*{original}*"})
                    if translated:  # Only send if there is translation content
                        messages.append({"content": titles["image_translation"]})
                        messages.append({"content": translated})
            else:
                # Process normal text translation
                if not original.startswith(("Notes: ")):
                    messages.append({"content": titles["original_content"]})
                    if original:
                        messages.append({"content": f"*{original}*"})
                    if translated:
                        # Clean translated content from original content
                        translated_lines = translated.split('\n')
                        original_lines = original.split('\n')
                        # Only keep lines not in original content
                        cleaned_translated = '\n'.join(
                            line for line in translated_lines 
                            if line not in original_lines
                        )
                        if cleaned_translated.strip():
                            messages.append({"content": titles["text_translation"]})
                            messages.append({"content": cleaned_translated})

            # Split long messages
            def split_message(content, limit=2000):
                if len(content) <= limit:
                    return [content]
                
                parts = []
                current_part = ""
                
                # Split by line
                lines = content.split('\n')
                
                for line in lines:
                    # If adding new line exceeds limit
                    if len(current_part) + len(line) + 1 > limit:
                        if current_part:
                            parts.append(current_part)
                        current_part = line
                    else:
                        if current_part:
                            current_part += '\n'
                        current_part += line
                
                if current_part:
                    parts.append(current_part)
                    
                return parts

            # Process message sending
            for msg in messages:
                if "file" in msg:
                    sent_message = await channel.send(content=msg["content"], file=msg["file"])
                    self.logger.info(f"Sent message with file to {channel_name}: {msg['content']}")
                else:
                    # Check message length and split
                    content_parts = split_message(msg["content"])
                    for part in content_parts:
                        sent_message = await channel.send(content=part)
                        self.logger.info(f"Sent message part to {channel_name}: {part}")

            # If there are notes, send them separately at the end
            if notes and not self._is_notes_empty(notes):
                # Remove possible "Notes: " prefix
                cleaned_notes = notes
                if cleaned_notes.startswith("Notes: "):
                    cleaned_notes = cleaned_notes[7:]  # Remove "Notes: " prefix
                # Send notes title first
                await channel.send(content=titles["notes"])
                # Then send notes content (without Notes: prefix)
                sent_message = await channel.send(f"*{cleaned_notes}*")
                self.logger.info(f"Sent notes to channel {channel.name}: {cleaned_notes}")

        except discord.errors.HTTPException as e:
            if e.code == 50035:  # Message length error
                self.logger.error(f"Message too long, attempting to split and resend")
                raise  # Still raise exception to trigger error handling
            else:
                self.logger.error(f"Discord HTTPException: {str(e)}")
                raise

    async def handle_attachments(self, attachments, target_channel):
        """Process attachments in messages"""
        self.logger.debug(f"Attachment count: {len(attachments)}")
        for index, attachment in enumerate(attachments, start=1):
            self.logger.debug(f"Processing attachment {index}: {attachment.to_dict()}")
            if attachment.content_type and attachment.content_type.startswith('image/'):
                self.logger.debug(f"Processing attachment image: {attachment.url}")
                try:
                    translated_image = await self.translator.translate_image(attachment.url)
                    self.logger.debug(f"Attachment image translation result: {translated_image}")
                    if translated_image:
                        await self.send_translation_result(
                            target_channel,
                            translated_image.get("original"),
                            translated_image.get("translation"),
                            notes=translated_image.get("notes"),
                            image_url=attachment.url
                        )
                        self.logger.info("Attachment image translation completed")
                except Exception as e:
                    self.logger.error(f"Error translating attachment image: {str(e)}", exc_info=True)
            else:
                self.logger.debug(f"Current attachment is not an image or missing content_type: {attachment.url}")

    async def fetch_referenced_message(self, message):
        """Fetch referenced message"""
        referenced_message = None
        if hasattr(message, 'reference') and message.reference:
            self.logger.info(f"Found referenced message, ID: {message.reference.message_id}, Channel ID: {message.reference.channel_id}")
            try:
                if hasattr(message.reference, 'resolved') and message.reference.resolved:
                    referenced_message = message.reference.resolved
                    self.logger.info("Successfully fetched referenced message from resolved property")
                else:
                    ref_channel = self.get_channel(message.reference.channel_id)
                    if ref_channel:
                        try:
                            referenced_message = await ref_channel.fetch_message(message.reference.message_id)
                            self.logger.info("Successfully fetched referenced message from referenced channel")
                        except discord.NotFound:
                            self.logger.warning(f"Message not found in channel {message.reference.channel_id}: {message.reference.message_id}")
                        except discord.Forbidden:
                            self.logger.warning(f"No permission to fetch message from channel {message.reference.channel_id}")
                        except Exception as e:
                            self.logger.warning(f"Failed to fetch referenced message: {str(e)}")
                    
                    if not referenced_message:
                        try:
                            referenced_message = await message.channel.fetch_message(message.reference.message_id)
                            self.logger.info("Successfully fetched referenced message from current channel")
                        except Exception as e:
                            self.logger.warning(f"Failed to fetch referenced message from current channel: {str(e)}")
            except Exception as e:
                self.logger.error(f"Error processing message reference: {str(e)}", exc_info=True)
        return referenced_message



    """ COMMANDS MANAGEMENT """

    @require_permissions('administrator')            
    async def set_translation_channel(
        self,
        interaction: Interaction,
        target_channel: discord.TextChannel = None
    ):
        """Set current channel as translation source channel, optionally another target channel"""

        source_channel_id = interaction.channel_id
        target_channel_id = target_channel.id if target_channel else source_channel_id
        
        self.translation_channels[source_channel_id] = target_channel_id
        self.save_translation_channels()
        
        if target_channel_id == source_channel_id:
            await interaction.response.send_message(
                "All messages in this channel will be translated.",
                ephemeral=True
            )
        else:
            source_channel = self.get_channel(source_channel_id)
            target_channel = self.get_channel(target_channel_id)
            await interaction.response.send_message(
                f"Translation forwarding set from {source_channel.mention} to {target_channel.mention}.",
                ephemeral=True
            )

    @require_permissions('administrator')
    async def remove_translation_channel(
        self,
        interaction: Interaction
    ):
        """Remove translation feature from current channel"""

        channel_id = interaction.channel_id
        
        # Check if it's a source or target channel
        is_source = channel_id in self.translation_channels
        is_target = channel_id in self.translation_channels.values()
        
        if not (is_source or is_target):
            await interaction.response.send_message(
                "This channel is not set up for translation.",
                ephemeral=True
            )
            return
            
        # Remove all related mappings
        if is_source:
            del self.translation_channels[channel_id]
        if is_target:
            # Find and remove all mappings pointing to this channel
            source_channels = [k for k, v in self.translation_channels.items() if v == channel_id]
            for source_channel in source_channels:
                del self.translation_channels[source_channel]
        
        self.save_translation_channels()
        await interaction.response.send_message(
            "Translation feature removed from this channel.",
            ephemeral=True
        )

    @require_permissions('administrator')
    async def list_translation_channels(
        self,
        interaction: Interaction
    ):
        """List all translation channel mappings"""
        try:
            if not self.translation_channels:
                await interaction.response.send_message(
                    "No translation channels set.",
                    ephemeral=True
                )
                return
            
            # Build mapping message
            mappings = []
            for source_id, target_id in self.translation_channels.items():
                source_channel = self.get_channel(source_id)
                target_channel = self.get_channel(target_id)
                
                if source_channel and target_channel:
                    if source_id == target_id:
                        mappings.append(f"- {source_channel.mention} (Self-translation)")
                    else:
                        mappings.append(f"- {source_channel.mention} ➜ {target_channel.mention}")
                else:
                    # Handle case where channel is not found
                    source_name = source_channel.mention if source_channel else f"Unknown channel ({source_id})"
                    target_name = target_channel.mention if target_channel else f"Unknown channel ({target_id})"
                    mappings.append(f"- {source_name} ➜ {target_name}")
            
            # Send response
            response = "**Current translation channel mappings:**\n" + "\n".join(mappings)
            await interaction.response.send_message(
                response,
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Failed to list translation channels: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                "Failed to get translation channel list.",
                ephemeral=True
            )

    @require_permissions('manage_messages')
    async def block_user(
        self,
        interaction: Interaction,
        user: discord.User
    ):        
        # Automatically determine type
        block_type = "bot" if user.bot else "user"
            
        self.blocked_users.append({
            "id": user.id,
            "type": block_type,
            "blocked_by": interaction.user.id,
            "blocked_at": datetime.now().isoformat()
        })
        self.save_blocked_users()
        
        await interaction.response.send_message(
            f"Blocked {user.mention} ({block_type})",
            ephemeral=True
        )

    @require_permissions('manage_messages')
    async def unblock_user(
        self,
        interaction: Interaction,
        user: discord.User
    ):          
        # Check if user is in blocked list
        is_blocked = any(block["id"] == user.id for block in self.blocked_users)
        if not is_blocked:
            await interaction.response.send_message(
                f"{user.mention} is not in the blocked list.",
                ephemeral=True
            )
            return
            
        self.blocked_users = [
            block for block in self.blocked_users 
            if block["id"] != user.id
        ]
        self.save_blocked_users()
        
        await interaction.response.send_message(
            f"Unblocked translation for {user.mention}",
            ephemeral=True
        )
    
    @app_commands.describe(webhook_id="ID of the webhook to block (required)")
    @require_permissions('manage_webhooks')
    async def block_webhook(
        self,
        interaction: Interaction,
        webhook_id: str
    ):
        try:
            webhook_id = int(webhook_id)
            
            if any(
                str(block["id"]) == str(webhook_id) and block["type"] == "webhook"
                for block in self.blocked_users
            ):
                await interaction.response.send_message(f"Webhook {webhook_id} is already blocked", ephemeral=True)
                return

            self.blocked_users.append({
                "id": webhook_id,
                "type": "webhook",
                "name": str(webhook_id), 
                "blocked_by": interaction.user.id,
                "blocked_at": datetime.utcnow().isoformat(),
            })
            self.save_blocked_users()
            await interaction.response.send_message(f"Blocked webhook: {webhook_id}", ephemeral=True)

        except ValueError:
            await interaction.response.send_message("Invalid webhook ID", ephemeral=True)
        except Exception as e:
            await self.send_error_message(str(e))

    @app_commands.describe(webhook_id="ID of the webhook to unblock (required)")  
    @require_permissions('manage_webhooks')
    async def unblock_webhook(
        self,
        interaction: Interaction,
        webhook_id: str
    ):
        """Unblock webhook"""


        try:
            webhook_id = int(webhook_id)
            blocked_webhook = next(
                (block for block in self.blocked_users 
                 if str(block["id"]) == str(webhook_id) and block["type"] == "webhook"), 
                None
            )
            
            if blocked_webhook:
                self.blocked_users.remove(blocked_webhook)
                self.save_blocked_users()
                await interaction.response.send_message(
                    f"Unblocked webhook: {blocked_webhook['name']}", 
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Webhook with ID {webhook_id} is not blocked", 
                    ephemeral=True
                )

        except ValueError:
            await interaction.response.send_message("Invalid webhook ID", ephemeral=True)
        except Exception as e:
            await self.send_error_message(str(e))
    
    @require_permissions('administrator')
    async def list_blocks(
        self,
        interaction: Interaction
    ):
        if not self.blocked_users:
            await interaction.response.send_message(
                "No blocked records found.",
                ephemeral=True
            )
            return
            
        blocks_list = []
        for block in self.blocked_users:
            try:
                if block["type"] == "webhook":
                    # If it's a webhook, use the saved name directly
                    blocks_list.append(
                        f"- Webhook: {block['name']} (ID: {block['id']})"
                    )
                else:
                    # If it's a user or bot, try to fetch user information
                    try:
                        user = await self.fetch_user(block["id"])
                        blocks_list.append(
                            f"- {user.mention} ({block['type']})"
                        )
                    except discord.NotFound:
                        # If user doesn't exist, show ID
                        blocks_list.append(
                            f"- Unknown {block['type'].capitalize()}: {block['id']}"
                        )
            except Exception as e:
                self.logger.error(f"Error processing blocked record: {str(e)}")
                continue
            
        if blocks_list:
            await interaction.response.send_message(
                "**Blocked List:**\n" + "\n".join(blocks_list),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Failed to retrieve blocked list information.",
                ephemeral=True
            )

    @require_permissions('administrator')
    async def add_glossary_term(
        self,
        interaction: Interaction,
        original: str,
        translation: str
    ):
        """Add glossary term"""

        try:
            # Use flattened dictionary format directly
            try:
                with open('translation_dictionary.json', 'r', encoding='utf-8') as f:
                    dictionary = json.load(f)
            except FileNotFoundError:
                dictionary = {}
            
            # Add new translation
            dictionary[original] = translation
            
            # Save updated dictionary
            with open('translation_dictionary.json', 'w', encoding='utf-8') as f:
                json.dump(dictionary, f, ensure_ascii=False, indent=4)
            
            # Reload translation dictionary
            self.translator.translation_dict = dictionary
            
            await interaction.response.send_message(
                f"Added term:\n{original} -> {translation}",
                ephemeral=True
            )
            
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to add term: {str(e)}",
                ephemeral=True
            )

    @require_permissions('administrator')
    async def remove_glossary_term(
        self,
        interaction: Interaction,
        original: str
    ):
        """Remove glossary term"""

        try:
            # Load current dictionary
            with open('translation_dictionary.json', 'r', encoding='utf-8') as f:
                dictionary = json.load(f)
                
            # Remove term
            if original in dictionary:
                del dictionary[original]
                
                # Save updated dictionary
                with open('translation_dictionary.json', 'w', encoding='utf-8') as f:
                    json.dump(dictionary, f, ensure_ascii=False, indent=4)
                
                # Reload translation dictionary
                self.translator.translation_dict = dictionary
                
                await interaction.response.send_message(
                    f"Deleted term: {original}",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Term not found: {original}",
                    ephemeral=True
                )
                
        except Exception as e:
            await interaction.response.send_message(
                f"Failed to delete term: {str(e)}",
                ephemeral=True
            )

    @require_permissions('administrator')
    async def list_glossary(
        self,
        interaction: Interaction
    ):
        """List all glossary terms"""
        try:
            # Use the dictionary already loaded in translator
            dictionary = self.translator.translation_dict
            
            if not dictionary:
                await interaction.response.send_message(
                    "Glossary is empty.",
                    ephemeral=True
                )
                return
            
            # Build response message
            response = ["**Glossary Terms:**"]
            for original, translation in sorted(dictionary.items()):
                response.append(f"- {original} -> {translation}")
            
            await interaction.response.send_message(
                "\n".join(response),
                ephemeral=True
            )
            
        except Exception as e:
            self.logger.error(f"Failed to list glossary: {str(e)}", exc_info=True)
            await interaction.response.send_message(
                f"Failed to get glossary: {str(e)}",
                ephemeral=True
            )

    @require_permissions('administrator')
    async def add_skip_keyword(self, interaction: Interaction, keyword: str):
        """Add a skip keyword"""
        try:
            if keyword.lower() in [k.lower() for k in self.translator.skip_keywords]:
                await interaction.response.send_message(f"Keyword `{keyword}` already exists.", ephemeral=True)
                return
            
            self.translator.skip_keywords.append(keyword)
            with open('skip_keywords.json', 'w', encoding='utf-8') as f:
                json.dump({"keywords": self.translator.skip_keywords}, f, ensure_ascii=False, indent=4)
            
            await interaction.response.send_message(f"Added keyword `{keyword}`.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to add skip keyword: {str(e)}", exc_info=True)
            await interaction.response.send_message("Failed to add keyword.", ephemeral=True)

    @require_permissions('administrator')
    async def remove_skip_keyword(self, interaction: Interaction, keyword: str):
        """Remove a skip keyword"""
        try:
            original_length = len(self.translator.skip_keywords)
            self.translator.skip_keywords = [k for k in self.translator.skip_keywords if k.lower() != keyword.lower()]
            
            if len(self.translator.skip_keywords) == original_length:
                await interaction.response.send_message(f"Keyword `{keyword}` not found.", ephemeral=True)
                return
            
            with open('skip_keywords.json', 'w', encoding='utf-8') as f:
                json.dump({"keywords": self.translator.skip_keywords}, f, ensure_ascii=False, indent=4)
            
            await interaction.response.send_message(f"Deleted keyword `{keyword}`.", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to delete skip keyword: {str(e)}", exc_info=True)
            await interaction.response.send_message("Failed to delete keyword.", ephemeral=True)

    @require_permissions('administrator')
    async def list_skip_keywords(self, interaction: Interaction):
        """List all skip keywords"""
        try:
            if not self.translator.skip_keywords:
                await interaction.response.send_message("No skip keywords set.", ephemeral=True)
                return
            
            keywords_formatted = "\n".join([f"- {k}" for k in self.translator.skip_keywords])
            await interaction.response.send_message(f"**Current skip keywords:**\n{keywords_formatted}", ephemeral=True)
        except Exception as e:
            self.logger.error(f"Failed to list skip keywords: {str(e)}", exc_info=True)
            await interaction.response.send_message("Failed to get keyword list.", ephemeral=True)



    """ TEXT CHECKING """

    def _contains_chars(self, text: str, char_type: str) -> bool:
        """General character detection function"""
        pattern = re.compile(self.CHAR_RANGES[char_type])
        return bool(pattern.search(text))

    def contains_chinese(self, text: str) -> bool:
        """Check if text contains Chinese characters"""
        return self._contains_chars(text, 'chinese')

    def contains_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters"""
        return self._contains_chars(text, 'japanese')

    def contains_korean(self, text: str) -> bool:
        """Check if text contains Korean characters"""
        return self._contains_chars(text, 'korean')

    def should_skip_chinese(self, text: str) -> bool:
        """Check if text should be skipped"""
        has_chinese = self.contains_chinese(text)
        has_japanese = self.contains_japanese(text)
        has_korean = self.contains_korean(text)
        
        return has_chinese and not (has_japanese or has_korean)

    def contains_only_special_characters(self, text: str) -> bool:
        """Check if text contains only special content (symbols, numbers, URLs, emojis)"""
        # Split into components first to handle URLs properly
        components = text.split()

        # Check each component
        for component in components:
            # Skip empty components
            if not component:
                continue
            
            # Check if it's a URL
            if re.match(self.url_pattern, component):
                continue
            
            # Check if it's a Discord custom emoji
            if re.match(self.discord_emoji_pattern, component):
                continue
            
            # Check if it's a standard Unicode emoji
            if all(c in emoji.EMOJI_DATA for c in component):
                continue
            
            # Check if it only contains special characters (punctuation, numbers, etc.)
            cleaned = re.sub(r'[\u3000-\u303F\uFF00-\uFFEF\d!"#$%&\'()*+,-./:;<=>?@\[\]^_`{|}~⚡️]', '', component)
            if not cleaned.strip():
                continue
            
            # If any component doesn't meet the above conditions, there's actual text content
            return False
        
        # All components are special content
        return True

    def _is_notes_empty(self, notes: str) -> bool:
        """Check if notes are empty or meaningless"""
        # Check if it's None or empty string
        if not notes:
            return True

        # Clean content and check against EMPTY_CONTENT_INDICATORS
        fully_cleaned = re.sub(r'[\s!"#$%&\'()*+,\-./:;<=>?@\[\]^_`{|}~。，！？；：""\']+', '', notes.lower())
        
        if fully_cleaned in EMPTY_INDICATORS:
            return True

        # Check if anything remains after cleaning
        return not fully_cleaned



    """ SAVING DATA """

    def save_translation_channels(self):
        """Save translation channel mappings to file"""
        try:
            with open('translation_channels.json', 'w') as f:
                # Convert integer keys to strings for JSON serialization
                channels_dict = {str(k): v for k, v in self.translation_channels.items()}
                json.dump(channels_dict, f)
        except Exception as e:
            self.logger.error(f"Failed to save translation channels: {str(e)}")

    def save_blocked_users(self):
        """Save blocked list to file"""
        try:
            with open(self.blocked_users_file, 'w') as f:
                json.dump(self.blocked_users, f)
        except Exception as e:
            self.logger.error(f"Failed to save blocked users: {str(e)}")



    """ CLEANUP """

    async def _do_whitelist_update(self):
        """Execute a single DM whitelist update"""
        try:
            self.logger.debug(f"Starting DM whitelist update. Guilds count: {len(self.guilds)}")

            if len(self.guilds) == 0:
                self.logger.warning("No guilds found. Bot may not be in any servers.")
                self.dm_whitelist = set()
                self.save_dm_whitelist()
                return

            # Collect all unique user IDs from all guilds
            user_ids = set()
            for guild in self.guilds:
                self.logger.debug(f"Processing guild: {guild.name} (ID: {guild.id}), member_count: {guild.member_count}")
                member_count = 0
                human_count = 0
                try:
                    # Fetch all members to ensure we have the complete list
                    async for member in guild.fetch_members(limit=None):
                        member_count += 1
                        if not member.bot:  # Only human users
                            user_ids.add(str(member.id))
                            human_count += 1
                            self.logger.debug(f"Added human user: {member.name} (ID: {member.id})")
                    self.logger.debug(f"Guild {guild.name}: fetched {member_count} members, {human_count} humans")
                except Exception as e:
                    self.logger.error(f"Error fetching members from guild {guild.name}: {str(e)}", exc_info=True)

            self.dm_whitelist = user_ids
            self.save_dm_whitelist()
            self.logger.info(f"Updated DM whitelist: {len(user_ids)} users from {len(self.guilds)} guilds")

        except Exception as e:
            self.logger.error(f"Error in whitelist update: {str(e)}", exc_info=True)

    async def _update_dm_whitelist(self):
        """Periodically update DM whitelist with all guild members (every 24 hours)"""
        try:
            await self.wait_until_ready()

            # Wait for the first manual update triggered by on_connect to complete
            # The on_connect waits 2 seconds then triggers update, so we wait longer
            await asyncio.sleep(15)

            # Then run periodic updates every 24 hours
            while True:
                await self._do_whitelist_update()
                # Wait 24 hours before next update
                await asyncio.sleep(86400)

        except asyncio.CancelledError:
            self.logger.info("DM whitelist update task cancelled")
        except Exception as e:
            self.logger.error(f"Error in whitelist update loop: {str(e)}", exc_info=True)

    async def _cleanup_messages(self):
        """Periodically clean expired messages"""
        while True:
            try:
                current_time = time.time()
                expired = [
                    k for k, v in self._message_cache.items()
                    if current_time - v > self.message_ttl
                ]
                for key in expired:
                    del self._message_cache[key]
                    
                # If cache is too large, delete oldest entries
                if len(self._message_cache) > self._max_cache_size:
                    sorted_items = sorted(self._message_cache.items(), key=lambda x: x[1])
                    for key, _ in sorted_items[:len(self._message_cache) - self._max_cache_size]:
                        del self._message_cache[key]
                    
                await asyncio.sleep(self._cache_cleanup_interval)
            except Exception as e:
                self.logger.error(f"Message cleanup error: {str(e)}")
                await asyncio.sleep(60)



    """ ERROR HANDLING """

    async def handle_queue_processor_error(self, task, retry_count=0, max_retries=None):
        """Error handling function for message queue processor, specifically for message processing task errors"""
        try:
            task.result()
        except asyncio.CancelledError:
            self.logger.warning("Message processing task cancelled")
        except Exception as e:
            await self.handle_global_error(e, "task", retry_count, task)

    async def handle_global_error(self, error: Exception, context: str = None, retry_count: int = 0, task=None):
        """Global error handling function, handles all types of errors and performs retry control"""
        try:
            max_retries = self.MAX_RETRY_ATTEMPTS
            error_msg = str(error)
            
            # Build error message based on context
            if context == "gateway":
                error_msg = f"Discord gateway connection error (attempt {retry_count + 1}/{max_retries}): {error_msg}"
            elif context == "task":
                error_msg = f"Message processing task error (attempt {retry_count + 1}/{max_retries}): {error_msg}"
            else:
                error_msg = f"Runtime error (attempt {retry_count + 1}/{max_retries}): {error_msg}"
            
            # Log error
            self.logger.error(error_msg, exc_info=True)
            
            # Handle retry logic
            if retry_count < max_retries:
                self.logger.info(f"Attempting retry... ({retry_count + 1}/{max_retries})")
                await asyncio.sleep(self.RETRY_DELAY)
                
                if context == "task" and task:
                    # Restart message processing task
                    self.message_processor_task = self.loop.create_task(self.process_message_queue())
                    self.message_processor_task.add_done_callback(
                        lambda t: asyncio.create_task(
                            self.handle_global_error(error, "task", retry_count + 1, t)
                        )
                    )
                return True
            
            # Max retry attempts reached
            self.logger.error(f"Max retry attempts ({max_retries}) reached")
            
            # Send error notification
            await self.send_error_message(
                f"Error after {max_retries} attempts: {error_msg}\n"
                f"Context: {context}"
            )
            
            # If it's a fatal error, close the program
            if context in ["gateway", "runtime"]:
                await self.close()
                sys.exit(1)
                
            return False
            
        except Exception as e:
            self.logger.error(f"Error in error handler: {str(e)}", exc_info=True)
            return False

    async def send_error_message(self, error_message):
        """Send error message to Discord"""
        self.logger.info("Preparing to send error message")
        
        # If it's a task error and needs to be restarted
        if hasattr(self, '_keep_running') and self._keep_running:
            self.logger.info("Restarting message processing task...")
            self.message_processor_task = self.loop.create_task(self.process_message_queue())
            self.message_processor_task.add_done_callback(
                lambda t: asyncio.create_task(self.handle_queue_processor_error(t, retry_count=0))
            )
        try:
            # Create error message
            embed = discord.Embed(
                title="Translation Error",
                description=error_message,
                color=discord.Color.red()
            ).set_footer(text="WalmartPapago")
        
            # 1. Try sending via webhook
            if ERROR_WEBHOOK_URL:
                try:
                    webhook = discord.Webhook.from_url(ERROR_WEBHOOK_URL, session=self.session)
                    await webhook.send(embed=embed)
                    self.logger.info("Error message sent to webhook")
                    return
                except Exception as e:
                    self.logger.error(f"Webhook error: {str(e)}", exc_info=True)
    
        
            # 2. Try sending to specified error channel
            if ERROR_CHANNEL_ID:
                try:
                    error_channel = self.get_channel(ERROR_CHANNEL_ID)
                    if error_channel:
                        await error_channel.send(embed=embed)
                        self.logger.info("Error message sent to specified error channel")
                        return
                except Exception as e:
                    self.logger.error(f"Failed to send to error channel: {str(e)}", exc_info=True)

        except Exception as e:
            self.logger.error(f"Error sending error message: {str(e)}", exc_info=True)



    """ EXIT HANDLING """

    def handle_exit(self, signum, frame):
        """Handle exit signal"""
        self.logger.info("Received exit signal, starting cleanup...")
        # Set running flag to False, indicating program should start exiting
        self._keep_running = False
        # Ensure async cleanup
        asyncio.create_task(self.close())

    async def close(self):
        """Cleanup resources when closing"""
        try:
            # Cancel and wait for cleanup task to complete
            if hasattr(self, 'cleanup_task') and self.cleanup_task:
                self.cleanup_task.cancel()
                try:
                    await self.cleanup_task
                except asyncio.CancelledError:
                    self.logger.info("Cleanup task cancelled successfully.")

            # Cancel and wait for whitelist update task to complete
            if hasattr(self, 'whitelist_update_task') and self.whitelist_update_task:
                self.whitelist_update_task.cancel()
                try:
                    await self.whitelist_update_task
                except asyncio.CancelledError:
                    self.logger.info("Whitelist update task cancelled successfully.")

            # Cancel and wait for message processing task to complete
            if hasattr(self, 'message_processor_task') and self.message_processor_task:
                self.message_processor_task.cancel()
                try:
                    await self.message_processor_task
                except asyncio.CancelledError:
                    self.logger.info("Message processor task cancelled successfully.")
            
            # Close translator's session if exists
            if hasattr(self, 'translator') and hasattr(self.translator, 'session'):
                if self.translator.session and not self.translator.session.closed:
                    await self.translator.session.close()
                    self.logger.info("Translator's aiohttp ClientSession closed successfully.")
            
            # Close bot's session
            if hasattr(self, 'session') and self.session and not self.session.closed:
                await self.session.close()
                self.logger.info("Bot's aiohttp ClientSession closed successfully.")
            
            # Close bot
            await super().close()
            self.logger.info("Bot closed successfully.")
            
        except Exception as e:
            self.logger.error(f"Cleanup error: {str(e)}", exc_info=True)

def main():
    ERROR_WEBHOOK_URL = os.getenv('ERROR_WEBHOOK_URL')

    bot = None
    for attempt in range(3):
        try:
            bot = TranslatorBot()
            bot._keep_running = True
            bot.logger.info("Starting bot...")
            
            try:
                bot.run(DISCORD_TOKEN)
                break  # Successfully running, exit loop
            except Exception as e:
                if not asyncio.run(bot.handle_global_error(e, "gateway", attempt)):
                    break
                
        except Exception as e:
            if not asyncio.run(bot.handle_global_error(e, "runtime", attempt)):
                break

if __name__ == "__main__":
    main() 