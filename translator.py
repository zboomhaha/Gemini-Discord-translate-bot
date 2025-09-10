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
from config import GEMINI_API_KEYS, SAFETY_SETTINGS, TRANSLATION_PROMPT, DEFAULT_TARGET_LANG, IMAGE_TRANSLATION_PROMPT, EMPTY_INDICATORS

class Translator:
    def __init__(self):
        """initialize translator"""
        self.logger = logging.getLogger(self.__class__.__name__)
        self._setup_rate_limits()
        
        self.api_keys = GEMINI_API_KEYS.copy()
        if not self.api_keys:
            self.logger.error("No API keys configured. Please set GEMINI_API_KEYS in environment variables.")
            raise ValueError("No API keys configured")
        
        self.setup_models()
        self.translation_dict_path = 'translation_dictionary.json'
        self.skip_keywords_path = 'skip_keywords.json'
        self.translation_dict = self.load_translation_dictionary()
        self.skip_keywords = self.load_skip_keywords()

    def _setup_rate_limits(self):
        """Set rate limit parameters"""
        self.request_semaphore = Semaphore(2)
        self.last_request_time = 0
        self.min_request_interval = 0.5
        self.max_retries = 3  

    def setup_models(self):
        """Initialize Gemini models, try available API keys in order"""
        

        # Convert safety settings from config to the required type
        self.safety_settings = [
            types.SafetySetting(
                category=types.HarmCategory[setting["category"]],
                threshold=types.HarmBlockThreshold[setting["threshold"]],
            )
            for setting in SAFETY_SETTINGS
        ]

        try:
            initialization_errors = []
            for key in self.api_keys:
                try:
                    # Initialize the client with the current key
                    client = genai.Client(api_key=key)
                    
                    # Test if the key is available by making a simple call
                    test_response = client.models.generate_content(
                        model="models/gemini-2.0-flash",
                        contents=["Test connection."],
                        config=types.GenerateContentConfig(
                            safety_settings=self.safety_settings
                        )
                    )

                    # If successful, set model names and confirm initialization
                    self.main_model_name = 'gemini-2.5-flash'
                    self.fallback_model_name = 'gemini-2.0-flash'
                    
                    self.logger.info(f"API key pool validated successfully.")
                    return
                    
                except Exception as e:
                    error_msg = f"Failed to initialize with a key: {str(e)}"
                    initialization_errors.append(error_msg)
                    self.logger.warning(error_msg)
                    continue
            
            # If all keys fail
            error_details = "\n".join(initialization_errors)
            error_msg = f"Failed to initialize client with any API key. Errors:\n{error_details}"
            self.logger.error(error_msg)
            raise Exception(error_msg)

        except Exception as e:
            self.logger.error(f"Failed to set up models: {str(e)}")
            raise

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
                self.logger.debug(f"Built translation prompt: {prompt}")
            except KeyError as ke:
                self.logger.error(
                    f"TRANSLATION_PROMPT formatting error: {ke}, parameter details: {format_params}"
                )
                raise Exception(f"Translation prompt formatting error: {ke}")
            
            async with aiohttp.ClientSession() as session:
                # Try main model
                result = await self._try_model(self.main_model_name, prompt)
                
                if result:
                    return result
                
                # If main model fails, try fallback model
                self.logger.warning("Primary model failed, switching to fallback model")
                result = await self._try_model(self.fallback_model_name, prompt)
                
                if result:
                    return result
                
                self.logger.error("Both primary and fallback models failed in text translation")
                raise Exception("Both primary and fallback models failed in text translation")
                    
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
                
                # 2. Prepare model input
                prompt = IMAGE_TRANSLATION_PROMPT.format(
                    target_lang=target_lang,
                    glossary_rules=self._build_glossary_prompt(),
                    skip_keywords=", ".join(self.skip_keywords)
                )
                # Convert image to bytes and prepare for API
                buffer = io.BytesIO()
                image.save(buffer, format='JPEG', quality=95)
                image_bytes = buffer.getvalue()
                image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
                
                # 3. Try main model
                result = await self._try_model(self.main_model_name, prompt, additional_data=image_part)
                if result:
                    return result
                
                # 4. Try fallback model
                self.logger.info("Primary model failed, trying fallback model")
                result = await self._try_model(self.fallback_model_name, prompt, additional_data=image_part)
                
                if result:
                    return result
                
                self.logger.error("Both primary and fallback models failed in image translation")
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

    async def _try_model(self, model_name: str, prompt: str, additional_data: Optional[types.Part] = None) -> Optional[Dict]:
        """Generic model attempt method"""
        try:
            self.logger.info(f"Attempting translation with model: {model_name}")
            if additional_data:
                self.logger.debug(f"Sending additional data...")

            # Set temperature and base generation config
            gen_config_params = {}
            if additional_data:
                gen_config_params.update({
                    "candidate_count": 1,
                    "temperature": 1.0,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                })
            else:
                gen_config_params.update({
                    "candidate_count": 1,
                    "temperature": 1.2,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": 8192,
                })

            # Prepare contents
            contents = [prompt, additional_data] if additional_data else [prompt]

            async def generate_content_call(client):
                # Specific config for gemini-2.5-flash
                if model_name == 'gemini-2.5-flash':
                    config = types.GenerateContentConfig(
                        **gen_config_params,
                        safety_settings=self.safety_settings,
                        thinking_config=types.ThinkingConfig(thinking_budget=0)
                    )
                else:
                    # For other models, do not include thinking_config
                    config = types.GenerateContentConfig(
                        **gen_config_params,
                        safety_settings=self.safety_settings
                    )

                partial_func = functools.partial(
                    client.models.generate_content,
                    model=f"models/{model_name}",
                    contents=contents,
                    config=config
                )
                
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, partial_func)

            response = await self._rate_limited_request(generate_content_call)

            # Add raw response log
            self.logger.debug(f"Raw Gemini response: {response}")

            if response.prompt_feedback and response.prompt_feedback.block_reason:
                self.logger.warning(
                    f"Translation blocked: {response.prompt_feedback.block_reason}, "
                    f"Model: {model_name}, "
                    f"Full feedback: {response.prompt_feedback}"
                )
                return None

            result_text = response.text if hasattr(response, 'text') else str(response)
            self.logger.info(f"Translation successful with model: {model_name}")
            return self._parse_translation_response(result_text, is_image=bool(additional_data))

        except Exception as e:
            self.logger.error(
                f"Model translation failed: {str(e)}，模型: {model_name}",
                exc_info=True
            )
            return None

    async def _rate_limited_request(self, coro_func):
        """Use semaphore and time interval to limit request rate"""
        retry_count = 0
        last_error = None
        
        while retry_count < self.max_retries:
            async with self.request_semaphore:
                current_time = asyncio.get_running_loop().time()
                time_since_last = current_time - self.last_request_time
                if time_since_last < self.min_request_interval:
                    self.logger.info(
                        f"Waiting {self.min_request_interval - time_since_last:.2f} seconds to meet minimum request interval"
                    )
                    await asyncio.sleep(self.min_request_interval - time_since_last)
                
                available_keys = self.api_keys.copy()
                while available_keys:
                    selected_key = random.choice(available_keys)
                    try:
                        request_client = genai.Client(api_key=selected_key)
                        self.last_request_time = asyncio.get_running_loop().time()
                        return await coro_func(client=request_client)
    
                    except Exception as e:
                        last_error = e
                        if "429" in str(e):
                            available_keys.remove(selected_key)
                            self.logger.warning(f"API key rate limit reached, switching to another key... ({len(available_keys)} remaining)")
                            if not available_keys:
                                break
                        elif "API key" in str(e) and ("not found" in str(e) or "invalid" in str(e)):
                            available_keys.remove(selected_key)
                            self.logger.error(f"Invalid API key removed from pool temporarily. ({len(available_keys)} remaining)")
                            if not available_keys:
                                raise ValueError("No valid API keys available") from e
                        else:
                            self.logger.error(
                                f"Unexpected error occurred during request: {str(e)}",
                                exc_info=True
                            )
                            raise
                
            retry_count += 1
            if retry_count < self.max_retries:
                wait_time = min(2 ** retry_count, 3)  # Exponential backoff, max wait 3 seconds
                self.logger.warning(f"All keys rate limited. Retrying in {wait_time}s... (Attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(wait_time)
        
        self.logger.error(
            f"Reached maximum retry count ({self.max_retries}) in _rate_limited_request, last error: {str(last_error)}"
        )
        raise Exception(f"Reached maximum retry count ({self.max_retries}). Last error: {str(last_error)}")

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


