import logging
import io
import aiohttp
import json
import random
import asyncio
import functools
from google import genai
from google.genai import types
from asyncio import Semaphore
from typing import Dict, Optional, List
from PIL import Image
from datetime import datetime
import discord
import time
from config import PROVIDERS_CONFIG, SAFETY_SETTINGS, TRANSLATION_PROMPT, DEFAULT_TARGET_LANG, IMAGE_TRANSLATION_PROMPT, EMPTY_INDICATORS, ERROR_WEBHOOK_URL


class ModelCooldownError(Exception):
    """Raised when model should enter cooldown (e.g., 503)"""
    pass


class BaseProvider:
    """Abstract base class for translation providers"""
    def __init__(self, name: str, config: Dict):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"{self.__class__.__name__}.{name}")
        self.api_keys = config.get('api_keys', [])
        # models config: [{"name": "model_name", "rpm": 5}, ...]
        self.models_config = config.get('models', [])
        
        # Per-(model, key) rate limiters for per-key RPM control
        self.rate_limiters = {}
        for model_cfg in self.models_config:
            model_name = model_cfg['name']
            rpm = model_cfg.get('rpm', 5)
            for key in self.api_keys:
                self.rate_limiters[(model_name, key)] = {
                    "semaphore": Semaphore(1),
                    "last_call_time": 0,
                    "interval": 60.0 / rpm if rpm > 0 else 0,
                    "rpm": rpm
                }
        
        # Model cooldown tracking: model_name -> cooldown_until (timestamp)
        self.model_cooldowns = {}
        
        # Disabled keys (invalid/expired), persists within session
        self.disabled_keys = set()
            
    async def generate_content(self, model_name: str, prompt: str, image_data: bytes = None) -> Optional[str]:
        raise NotImplementedError

    async def _check_rate_limit(self, model_name: str, key: str):
        """Enforce per-key RPM limit"""
        limiter = self.rate_limiters.get((model_name, key))
        if not limiter:
            return
            
        async with limiter["semaphore"]:
            current_time = asyncio.get_running_loop().time()
            time_since_last = current_time - limiter["last_call_time"]
            
            if time_since_last < limiter["interval"]:
                wait_time = limiter["interval"] - time_since_last
                self.logger.debug(f"Rate limit: Waiting {wait_time:.2f}s for {model_name} key {key[:8]}...")
                await asyncio.sleep(wait_time)
            
            limiter["last_call_time"] = asyncio.get_running_loop().time()

    def _get_available_keys(self) -> list:
        """Get keys that are not disabled"""
        return [k for k in self.api_keys if k not in self.disabled_keys]

    def _check_model_cooldown(self, model_name: str):
        """Check if model is in cooldown, raise ModelCooldownError if so"""
        if model_name in self.model_cooldowns:
            if time.time() < self.model_cooldowns[model_name]:
                remaining = int(self.model_cooldowns[model_name] - time.time())
                raise ModelCooldownError(
                    f"Model {model_name} is in cooldown ({remaining}s remaining)"
                )
            else:
                del self.model_cooldowns[model_name]

    async def _send_key_error_webhook(self, key: str, error_msg: str):
        """Send error webhook for invalid/expired key"""
        try:
            if not ERROR_WEBHOOK_URL:
                return
            async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(ERROR_WEBHOOK_URL, session=session)
                embed = discord.Embed(
                    title="🔑 API Key Error",
                    description=f"Provider **{self.name}** key `{key[:12]}...` is invalid/expired.\n\nError: {error_msg[:500]}",
                    color=0xFF0000
                )
                embed.set_footer(text=f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                await webhook.send(embed=embed)
                self.logger.info(f"Key error webhook sent for key {key[:8]}...")
        except Exception as e:
            self.logger.error(f"Failed to send key error webhook: {str(e)}")

class OfficialProvider(BaseProvider):
    """Provider for Google Official SDK (google-genai)"""
    def __init__(self, name: str, config: Dict, safety_settings: List):
        super().__init__(name, config)
        self.safety_settings = safety_settings
        
    async def generate_content(self, model_name: str, prompt: str, image_data: bytes = None) -> Optional[str]:
        # Check model cooldown first
        self._check_model_cooldown(model_name)
        
        available_keys = self._get_available_keys()
        if not available_keys:
            raise Exception(f"No available API keys for provider {self.name}")
        
        max_retries = min(3, len(available_keys))
        tried_keys = set()
        
        for attempt in range(max_retries):
            remaining = [k for k in available_keys if k not in tried_keys]
            if not remaining:
                break
            key = random.choice(remaining)
            tried_keys.add(key)
            
            self.logger.info(f"Trying key {key[:8]}... ({attempt + 1}/{max_retries}) for model {model_name}")
            
            try:
                await self._check_rate_limit(model_name, key)
                
                client = genai.Client(api_key=key)
                
                contents = [prompt]
                if image_data:
                    image_part = types.Part.from_bytes(data=image_data, mime_type='image/jpeg')
                    contents.append(image_part)
                
                gen_config_params = {
                    "candidate_count": 1,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                }
                
                if image_data:
                    gen_config_params.update({"temperature": 1.0})
                else:
                    gen_config_params.update({"temperature": 1.2})

                # Special config for gemini-2.5-flash
                if model_name == 'gemini-2.5-flash':
                     config = types.GenerateContentConfig(
                        **gen_config_params,
                        safety_settings=self.safety_settings,
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    )
                else:
                    config = types.GenerateContentConfig(
                        **gen_config_params,
                        safety_settings=self.safety_settings
                    )

                # Execute in executor with 10s timeout per API call
                partial_func = functools.partial(
                    client.models.generate_content,
                    model=f"models/{model_name}",
                    contents=contents,
                    config=config
                )
                loop = asyncio.get_running_loop()
                try:
                    response = await asyncio.wait_for(
                        loop.run_in_executor(None, partial_func),
                        timeout=10
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(f"API call timed out (10s) for key {key[:8]}... model {model_name}")
                    raise Exception(f"API call timeout (10s) for model {model_name}")
                
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    self.logger.warning(f"Blocked: {response.prompt_feedback}")
                    return None
                    
                return response.text if hasattr(response, 'text') else str(response)

            except ModelCooldownError:
                raise  # Re-raise cooldown errors
            except Exception as e:
                error_str = str(e)
                self.logger.warning(f"Key {key[:8]}... failed ({attempt + 1}/{max_retries}): {error_str}")
                
                # 503 - Model overloaded, cooldown entire model immediately
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    self.model_cooldowns[model_name] = time.time() + 300
                    self.logger.warning(f"Model {model_name} received 503, entering cooldown for 5 minutes")
                    raise ModelCooldownError(f"Model {model_name} unavailable (503), cooldown 5min")
                
                # 429 - Key rate limited, try next key
                elif "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    continue
                
                # 400/403 - Check if key-related error
                elif ("API_KEY_INVALID" in error_str or "API key expired" in error_str 
                      or "API key not valid" in error_str
                      or ("403" in error_str and "PERMISSION_DENIED" in error_str)):
                    self.disabled_keys.add(key)
                    self.logger.error(f"Key {key[:8]}... marked as disabled (invalid/expired)")
                    asyncio.create_task(self._send_key_error_webhook(key, error_str))
                    continue
                
                # Other errors - try next key
                else:
                    continue
        
        raise Exception(f"All attempted keys failed for provider {self.name}")

class CustomProvider(BaseProvider):
    """Provider for Custom Base URL (Raw HTTP)"""
    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)
        self.base_url = config.get('base_url', '').rstrip('/')
        if not self.base_url:
            raise ValueError(f"No base_url configured for custom provider {name}")
            
    async def generate_content(self, model_name: str, prompt: str, image_data: bytes = None) -> Optional[str]:
        # Check model cooldown first
        self._check_model_cooldown(model_name)
        
        available_keys = self._get_available_keys()
        if not available_keys:
            raise Exception(f"No available API keys for provider {self.name}")
        
        max_retries = min(3, len(available_keys))
        tried_keys = set()
        
        import base64
        
        for attempt in range(max_retries):
            remaining = [k for k in available_keys if k not in tried_keys]
            if not remaining:
                break
            key = random.choice(remaining)
            tried_keys.add(key)
            
            self.logger.info(f"Trying key {key[:8]}... ({attempt + 1}/{max_retries}) for model {model_name}")
            
            try:
                await self._check_rate_limit(model_name, key)
                
                url = f"{self.base_url}/v1beta/models/{model_name}:generateContent?key={key}"
                
                # Construct payload
                parts = [{"text": prompt}]
                if image_data:
                    b64_image = base64.b64encode(image_data).decode('utf-8')
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_image
                        }
                    })
                
                payload = {
                    "contents": [{"parts": parts}],
                    "generationConfig": {
                         "temperature": 1.0 if image_data else 1.2,
                         "topP": 0.95,
                         "topK": 40,
                         "maxOutputTokens": 8192,
                         "candidateCount": 1
                    }
                }
                
                timeout = aiohttp.ClientTimeout(total=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            try:
                                return data['candidates'][0]['content']['parts'][0]['text']
                            except (KeyError, IndexError):
                                return ""
                        
                        # Handle error responses by status code
                        error_text = await resp.text()
                        
                        if resp.status == 503:
                            self.model_cooldowns[model_name] = time.time() + 300
                            self.logger.warning(f"Model {model_name} received 503, entering cooldown for 5 minutes")
                            raise ModelCooldownError(f"Model {model_name} unavailable (503), cooldown 5min")
                        
                        elif resp.status == 429:
                            self.logger.warning(f"Key {key[:8]}... rate limited (429)")
                            raise Exception(f"HTTP 429: {error_text[:200]}")
                        
                        elif resp.status in (400, 403):
                            self.disabled_keys.add(key)
                            self.logger.error(f"Key {key[:8]}... marked as disabled (HTTP {resp.status})")
                            asyncio.create_task(self._send_key_error_webhook(key, f"HTTP {resp.status}: {error_text[:300]}"))
                            raise Exception(f"HTTP {resp.status}: {error_text[:200]}")
                        
                        else:
                            raise Exception(f"HTTP {resp.status}: {error_text[:200]}")

            except ModelCooldownError:
                raise  # Re-raise cooldown errors
            except Exception as e:
                self.logger.warning(f"Key {key[:8]}... failed ({attempt + 1}/{max_retries}): {str(e)}")
                continue
                
        raise Exception(f"All attempted keys failed for provider {self.name}")

class ProviderManager:
    def __init__(self, providers_config: Dict, safety_settings: List):
        self.logger = logging.getLogger("ProviderManager")
        self.providers = {}
        self.provider_order = providers_config.get('settings', {}).get('provider_order', [])
        
        # Initialize providers
        p_configs = providers_config.get('providers', {})
        for p_name, p_cfg in p_configs.items():
            try:
                p_type = p_cfg.get('type')
                if p_type == 'official':
                    self.providers[p_name] = OfficialProvider(p_name, p_cfg, safety_settings)
                elif p_type == 'custom':
                    self.providers[p_name] = CustomProvider(p_name, p_cfg)
                self.logger.info(f"Initialized provider: {p_name} ({p_type})")
            except Exception as e:
                self.logger.error(f"Failed to initialize provider {p_name}: {str(e)}")
        
        # Filter order to only existing providers
        self.provider_order = [p for p in self.provider_order if p in self.providers]
        if not self.provider_order and self.providers:
            # If no order specified but providers exist, add them arbitrarily
            self.provider_order = list(self.providers.keys())

    async def generate_with_fallback(self, prompt: str, image_data: bytes = None) -> str:
        """Try all providers in order, with model and provider fallback"""
        if not self.providers:
             raise Exception("No providers configured")

        errors = []
        
        for provider_name in self.provider_order:
            provider = self.providers[provider_name]
            self.logger.info(f"Using provider: {provider_name}")
            
            # Try all models in this provider
            for model_cfg in provider.models_config:
                model_name = model_cfg['name']
                try:
                    result = await provider.generate_content(model_name, prompt, image_data)
                    if result:
                         return result
                except ModelCooldownError as e:
                    # Model is in cooldown (503), skip to next model
                    self.logger.warning(f"Provider {provider_name} model {model_name} cooldown: {str(e)}")
                    errors.append(f"{provider_name}/{model_name}: {str(e)}")
                    continue
                except Exception as e:
                    self.logger.warning(f"Provider {provider_name} model {model_name} failed: {str(e)}")
                    errors.append(f"{provider_name}/{model_name}: {str(e)}")
                    continue
            
            # Provider failed all models/keys, send fallback webhook
            is_last = (provider_name == self.provider_order[-1])
            if not is_last and ERROR_WEBHOOK_URL:
                 next_provider = self.provider_order[self.provider_order.index(provider_name) + 1]
                 asyncio.create_task(self._send_fallback_webhook(provider_name, next_provider))
        
        raise Exception(f"All providers failed. Errors: {'; '.join(errors)}")

    async def _send_fallback_webhook(self, failed_provider: str, next_provider: str):
        try:
             async with aiohttp.ClientSession() as session:
                webhook = discord.Webhook.from_url(ERROR_WEBHOOK_URL, session=session)
                embed = discord.Embed(
                    title="⚠️ Provider Fallback",
                    description=f"Provider **{failed_provider}** exhausted (keys/rate limits). Switching to **{next_provider}**.",
                    color=0xFFA500 # Orange
                )
                embed.set_footer(text=f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                await webhook.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Failed to send fallback webhook: {str(e)}")

class Translator:
    def __init__(self):
        """initialize translator"""
        self.logger = logging.getLogger(self.__class__.__name__)
        
        # Load configs
        self.translation_dict_path = 'translation_dictionary.json'
        self.skip_keywords_path = 'skip_keywords.json'
        self.translation_dict = self.load_translation_dictionary()
        self.skip_keywords = self.load_skip_keywords()
        
        # Setup safety settings for OfficialProvider
        self.safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory[setting["category"]],
                threshold=types.HarmBlockThreshold[setting["threshold"]],
            )
            for setting in SAFETY_SETTINGS
        ]
        
        # Initialize ProviderManager
        self.manager = ProviderManager(PROVIDERS_CONFIG, self.safety_settings)
        
        # Suppress AFC (Automatic Function Calling) INFO logs
        logging.getLogger("google_genai.models").setLevel(logging.WARNING)

    def load_translation_dictionary(self):
        """Load translation dictionary"""
        try:
            with open(self.translation_dict_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
                # Validate data format
                if not isinstance(data, dict):
                    self.logger.error("Invalid dictionary format, resetting to empty dictionary")
                    data = {}
                    
                # Validate all key-value pairs
                validated_dict = {}
                for key, value in data.items():
                    if isinstance(key, str) and isinstance(value, str):
                        validated_dict[key] = value
                    else:
                        self.logger.warning(f"Skipping invalid dictionary entry: {key} -> {value}")
                
                # If validated dictionary is empty but original data is not empty, record error
                if not validated_dict and data:
                    self.logger.error("No valid entries found in dictionary")
                
                return validated_dict
                
        except FileNotFoundError:
            self.logger.warning("Glossary file not found, creating new empty glossary")
            empty_dict = {}
            with open(self.translation_dict_path, 'w', encoding='utf-8') as f:
                json.dump(empty_dict, f, ensure_ascii=False, indent=4)
            return empty_dict
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in dictionary file: {str(e)}")
            return {}
        except Exception as e:
            self.logger.error(f"Failed to load glossary: {str(e)}")
            return {}

    def load_skip_keywords(self):
        """Load skip keywords, create file if it doesn't exist"""
        try:
            with open(self.skip_keywords_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('keywords', [])
        except FileNotFoundError:
            self.logger.warning("Skip keywords file not found, creating new file")
            # Create default skip_keywords file
            default_keywords = {
                "keywords": []  # Default to empty list
            }
            try:
                with open(self.skip_keywords_path, 'w', encoding='utf-8') as f:
                    json.dump(default_keywords, f, ensure_ascii=False, indent=4)
                self.logger.info("Created new skip_keywords.json file")
                return default_keywords['keywords']
            except Exception as e:
                self.logger.error(f"Failed to create skip_keywords.json: {str(e)}")
                return []
        except Exception as e:
            self.logger.error(f"Failed to load skip keywords: {str(e)}")
            return [] 

    def _build_glossary_prompt(self) -> str:
        """Build glossary prompt"""
        try:
            if not self.translation_dict:
                return "No specific glossary rules."
            
            # Ensure translation_dict is in the correct format
            if not isinstance(self.translation_dict, dict):
                self.logger.error("Invalid translation dictionary format")
                return "Error: Invalid glossary format"
            
            # Build prompt, use safe string formatting
            glossary_rules = ["Additionally, you must strictly follow these translation rules:"]
            try:
                for original, translation in self.translation_dict.items():
                    if isinstance(original, str) and isinstance(translation, str):
                        # Escape characters that could cause formatting errors
                        safe_original = original.replace("{", "{{").replace("}", "}}")
                        safe_translation = translation.replace("{", "{{").replace("}", "}}")
                        glossary_rules.append(f"- Translate \"{safe_original}\" as \"{safe_translation}\"")
                    else:
                        self.logger.warning(f"Skipping invalid glossary entry: {original} -> {translation}")
            except Exception as e:
                self.logger.error(f"Error processing glossary entries: {str(e)}")
                return "Error processing glossary rules."
            
            return "\n".join(glossary_rules)
            
        except Exception as e:
            self.logger.error(f"Error building glossary prompt: {str(e)}")
            return "Error loading glossary rules."

    async def translate_text(self, text: str, target_lang: str = None) -> Dict:
        """Translate text"""
        target_lang = target_lang or DEFAULT_TARGET_LANG
        try:
            self.logger.info(f"Starting translation. Text length: {len(text)}, Target: {target_lang}")
            
            glossary_rules = self._build_glossary_prompt()
            
            # Escape characters that could cause formatting errors in input text
            safe_text = text.replace("{", "{{").replace("}", "}}")
            
            # Check and record formatting parameters
            format_params = {
                'target_lang': target_lang,
                'text': safe_text,
                'glossary_rules': glossary_rules
            }
            
            try:
                # Build full prompt
                prompt = TRANSLATION_PROMPT.format(**format_params)
            except KeyError as ke:
                self.logger.error(
                    f"TRANSLATION_PROMPT formatting error: {ke}, parameter details: {format_params}"
                )
                raise Exception(f"Translation prompt formatting error: {ke}")
            
            # Use Manager to execute
            result_text = await self.manager.generate_with_fallback(prompt)
            
            if result_text:
                 # Parse the result
                return self._parse_translation_response(result_text, is_image=False)
            
            raise Exception("Translation returned empty result")
                    
        except Exception as e:
            self.logger.error(
                f"Translation error in translate_text: {str(e)}",
                exc_info=True
            )
            raise Exception(f"Translation failed: {str(e)}") from e

    async def translate_image(self, image_url: str, target_lang: str = None) -> Dict:
        """Translate text in image"""
        try:
            target_lang = target_lang or DEFAULT_TARGET_LANG
            self.logger.info(f"Starting image translation. URL: {image_url}, Target: {target_lang}")
            
            # Use context manager to handle session lifecycle
            async with aiohttp.ClientSession() as session:
                # 1. Download and preprocess image
                image = await self._download_and_process_image(image_url, session)
                
                # 2. Prepare prompt
                prompt = IMAGE_TRANSLATION_PROMPT.format(
                    target_lang=target_lang,
                    glossary_rules=self._build_glossary_prompt(),
                    skip_keywords=", ".join(self.skip_keywords)
                )
                # Convert image to bytes
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=95)
                image_bytes = buffer.getvalue()
                
                # 3. Use Manager to execute
                result_text = await self.manager.generate_with_fallback(prompt, image_data=image_bytes)
                
                if result_text:
                    return self._parse_translation_response(result_text, is_image=True)

                return None
    
        except Exception as e:
            self.logger.error(f"Image translation error: {str(e)}", exc_info=True)
            raise Exception(f"Image translation failed: {str(e)}") from e

    async def _download_and_process_image(self, image_url: str, session: aiohttp.ClientSession) -> Image.Image:
        """Download and preprocess image"""
        try:
            async with session.get(image_url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download image: HTTP {response.status}")
                image_data = await response.read()
                image = Image.open(io.BytesIO(image_data))
                
                # Convert to RGB mode if necessary
                if image.mode != 'RGB':
                    image = image.convert('RGB')
                    
                return image
                
        except Exception as e:
            self.logger.error(f"Failed to download and process image: {str(e)}")
            raise

    def _parse_translation_response(self, response, is_image: bool = False) -> Dict:
        """Uniform response parsing function"""
        try:
            # Get response text
            if hasattr(response, 'text'):
                text = response.text
            elif hasattr(response, 'result'):
                text = response.result.text
            else:
                text = str(response)
            
            self.logger.debug(f"Parsing {'image' if is_image else 'text'} translation response: {text}...")
            
            # Initialize result dictionary
            result = {
                "original": "",
                "translation": "",
                "notes": None
            }
            
            # Use unified content collector
            current_section = None
            section_content = {
                "original": [],
                "translation": [],
                "notes": []
            }
            current_content = []
            
            # Process response text
            for line in (l.strip() for l in text.split('\n') if l.strip()):
                # Process paragraph marker
                if line.startswith("Original text:"):
                    self._append_content(current_content, current_section, section_content)
                    current_section = "original"
                    content = line.replace("Original text:", "").strip()
                    if content:
                        section_content["original"].append(content)
                    current_content = []
                elif line.startswith("Translation:"):
                    self._append_content(current_content, current_section, section_content)
                    current_section = "translation"
                    content = line.replace("Translation:", "").strip()
                    if content:
                        section_content["translation"].append(content)
                    current_content = []
                elif line.startswith("Notes:"):
                    self._append_content(current_content, current_section, section_content)
                    current_section = "notes"
                    content = line.replace("Notes:", "").strip()
                    if content:
                        section_content["notes"].append(content)
                    current_content = []
                # Process regular content line
                elif current_section:
                    current_content.append(line)
            
            # Process last section content
            self._append_content(current_content, current_section, section_content)
            
            # Merge results and clean empty lines
            for key in ["original", "translation"]:
                if section_content[key]:
                    result[key] = '\n'.join(
                        line for line in section_content[key] 
                        if line.strip()
                    )
                else:
                    result[key] = ""
            
            # Process notes
            if section_content["notes"]:
                result["notes"] = "Notes: " + "\n".join(section_content["notes"])
            else:
                result["notes"] = None
            
            # Define empty content indicators
            empty_content_indicators = EMPTY_INDICATORS
            
            # Check if content is empty
            def is_empty_content(text: str) -> bool:
                if not text or not text.strip():
                    return True
                cleaned_text = text.strip().lower()
                return any(cleaned_text == indicator.lower() for indicator in empty_content_indicators)
            
            # If content is empty, return no detection message
            if is_empty_content(result["original"]) or is_empty_content(result["translation"]):
                no_text_msg = "<未检测出文字>" if DEFAULT_TARGET_LANG == "zh-CN" else "<No text detected>"
                if is_image:
                    return {
                        "original": no_text_msg,
                        "translation": "",
                        "notes": None
                    }
                self.logger.warning(
                    f"{'Image' if is_image else 'Text'} translation result did not detect valid content"
                )
                return None
            
            self.logger.info(
                f"Parsed translation result: Original length={len(result['original'])}, Translation length={len(result['translation'])}, Notes exist={bool(result['notes'])}"
            )
            return result
                
        except Exception as e:
            self.logger.error(
                f"{'OCR' if is_image else 'Translation'} parsing failed: {str(e)}",
                exc_info=True
            )
            no_text_msg = "<未检测出文字>" if DEFAULT_TARGET_LANG == "zh-CN" else "<No text detected>"
            if is_image:
                return {
                    "original": no_text_msg,
                    "translation": "",
                    "notes": None
                }
            return None

    def _append_content(self, current_content: List[str], current_section: str, section_content: Dict[str, List[str]]) -> None:
        """Append current content to corresponding section"""
        if current_content and current_section:
            section_content[current_section].extend(current_content)


