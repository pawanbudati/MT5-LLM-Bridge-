import os
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
from telethon import TelegramClient, events, utils as telethon_utils
from colorama import Fore, Style

from config import settings
from models import PairConfig, PairMode, TaskMessage, TaskType

logger = logging.getLogger(__name__)

class MasterTelegramDispatcher:
    def __init__(self, pairs: List[PairConfig], pair_queues: Dict[int, Any]):
        self.pairs = pairs
        self.pair_queues = pair_queues  # {pair_id: multiprocessing.Queue}
        self.client: Optional[TelegramClient] = None
        # Mapping from various channel identifiers (normalized int ID, string ID) -> List[PairConfig]
        self.channel_pairs_map: Dict[str, List[PairConfig]] = {}
        self.subscribed_entities = []

    async def start(self):
        """Authenticate with Telegram, resolve all target channels, and register event handler."""
        if not settings.TELEGRAM_API_ID or not settings.TELEGRAM_API_HASH:
            raise ValueError(
                "TELEGRAM_API_ID or TELEGRAM_API_HASH is not set in .env! "
                "Please configure them from https://my.telegram.org in your .env file."
            )

        session_path = settings.BASE_DIR / settings.TELEGRAM_SESSION_NAME
        self.client = TelegramClient(str(session_path), settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)

        logger.info("Connecting to Telegram...")
        await self.client.start(phone=settings.TELEGRAM_PHONE)
        me = await self.client.get_me()
        logger.info(Fore.GREEN + f"Telegram Authenticated as: {getattr(me, 'first_name', '')} (@{getattr(me, 'username', 'N/A')})" + Style.RESET_ALL)

        # Resolve all channels for each pair
        await self._resolve_all_channels()

        if not self.subscribed_entities:
            logger.warning("No channels were successfully resolved! Bot will not receive channel signals.")
            return

        # Register unified new message event handler
        @self.client.on(events.NewMessage(chats=self.subscribed_entities))
        async def on_new_message(event):
            await self._handle_incoming_event(event)

        logger.info(Fore.GREEN + Style.BRIGHT + "\n" + "=" * 70)
        logger.info(f" [*] MASTER TELEGRAM LISTENER ACTIVE - LISTENING TO {len(self.subscribed_entities)} CHANNELS")
        for p in self.pairs:
            logger.info(f"     Pair #{p.id} [{p.name}]: Channel '{p.channel}' -> Mode: {p.mode.value.upper()}")
        logger.info("=" * 70 + "\n" + Style.RESET_ALL)

    async def run_until_disconnected(self):
        if self.client:
            await self.client.run_until_disconnected()

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
            logger.info("Telegram client disconnected.")

    async def _resolve_all_channels(self):
        """Iterate through configured pairs and resolve each Telegram channel."""
        dialogs = None

        for pair in self.pairs:
            target = pair.channel.strip()
            if not target:
                logger.warning(f"Pair #{pair.id} [{pair.name}] has no channel configured. Skipping.")
                continue

            entity = None
            # 1. Try direct resolution by numeric ID or username
            try:
                if target.startswith("-100") or (target.startswith("-") and target[1:].isdigit()) or target.isdigit():
                    entity_id = int(target)
                    entity = await self.client.get_entity(entity_id)
                else:
                    entity = await self.client.get_entity(target)
            except Exception as e:
                logger.info(f"Direct lookup for channel '{target}' ({pair.name}) did not succeed ({e}). Searching dialogs...")

            # 2. Search dialogs if direct lookup failed
            if not entity:
                if dialogs is None:
                    dialogs = await self.client.get_dialogs(limit=150)

                target_lower = target.lower().lstrip("@")
                for d in dialogs:
                    d_title = (d.title or "").strip().lower()
                    d_user = (getattr(d.entity, 'username', '') or "").strip().lower()
                    if d_title == target_lower or d_user == target_lower:
                        entity = d.entity
                        break

            if entity:
                # Add to subscribed entities for Telethon filter
                if entity not in self.subscribed_entities:
                    self.subscribed_entities.append(entity)

                # Store matching keys in lookup map
                raw_id = getattr(entity, 'id', None)
                norm_peer_id = telethon_utils.get_peer_id(entity)
                
                keys_to_register = set()
                if raw_id:
                    keys_to_register.add(str(raw_id))
                    keys_to_register.add(f"-100{raw_id}")
                    keys_to_register.add(f"-{raw_id}")
                if norm_peer_id:
                    keys_to_register.add(str(norm_peer_id))
                keys_to_register.add(target.lower())
                uname = getattr(entity, 'username', '')
                if uname:
                    keys_to_register.add(f"@{uname.lower()}")
                    keys_to_register.add(uname.lower())

                for k in keys_to_register:
                    if k not in self.channel_pairs_map:
                        self.channel_pairs_map[k] = []
                    if pair not in self.channel_pairs_map[k]:
                        self.channel_pairs_map[k].append(pair)

                title = getattr(entity, 'title', target)
                logger.info(Fore.GREEN + f"[+] Channel resolved: '{title}' (ID: {norm_peer_id}) -> Mapped to Pair #{pair.id} [{pair.name}]" + Style.RESET_ALL)
            else:
                logger.error(Fore.RED + f"[-] Could not resolve channel '{target}' for Pair #{pair.id} [{pair.name}]!" + Style.RESET_ALL)

    async def _handle_incoming_event(self, event):
        """Route incoming message to subscribed pair queues."""
        message = event.message
        chat_id = event.chat_id
        str_chat_id = str(chat_id)

        # Find matching pairs
        matching_pairs: List[PairConfig] = []
        for key in (str_chat_id, str_chat_id.replace("-100", ""), abs(chat_id)):
            str_k = str(key)
            if str_k in self.channel_pairs_map:
                for p in self.channel_pairs_map[str_k]:
                    if p not in matching_pairs:
                        matching_pairs.append(p)

        if not matching_pairs:
            logger.debug(f"Received message from non-mapped chat {chat_id}. Ignoring.")
            return

        has_photo = bool(message.photo)
        has_image_doc = bool(
            message.document and 
            message.document.mime_type and 
            message.document.mime_type.startswith("image/")
        )
        is_image_msg = has_photo or has_image_doc
        text_content = message.message or ""

        # Download image once if any matching pair requires an image
        downloaded_image_path = None
        needs_image = any(p.mode in (PairMode.IMAGE, PairMode.BOTH) for p in matching_pairs)
        if is_image_msg and needs_image:
            file_ext = ".jpg"
            if has_image_doc and message.document.mime_type:
                ext = message.document.mime_type.split("/")[-1]
                if ext in ("png", "jpeg", "webp"):
                    file_ext = f".{ext}"
            save_path = settings.DOWNLOADS_DIR / f"chart_msg_{message.id}_{int(time.time())}{file_ext}"
            try:
                logger.info(f"Downloading image media from chat {chat_id} (Msg #{message.id})...")
                downloaded = await message.download_media(file=str(save_path))
                if downloaded:
                    downloaded_image_path = str(save_path)
            except Exception as e:
                logger.error(f"Error downloading image media: {e}")

        # Fetch reply context if message is reply and text is needed
        reply_context = None
        needs_text = any(p.mode in (PairMode.TEXT, PairMode.BOTH) for p in matching_pairs)
        if event.is_reply and needs_text:
            try:
                reply_msg = await event.get_reply_message()
                if reply_msg and reply_msg.raw_text:
                    reply_context = reply_msg.raw_text
            except Exception as e:
                logger.warning(f"Could not fetch reply context: {e}")

        # Dispatch to respective pairs
        for pair in matching_pairs:
            q = self.pair_queues.get(pair.id)
            if not q:
                continue

            if pair.mode == PairMode.IMAGE:
                if downloaded_image_path:
                    task = TaskMessage(
                        task_type=TaskType.IMAGE_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        image_path=downloaded_image_path,
                        caption=text_content,
                        timestamp=time.time()
                    )
                    q.put(task)
                    logger.info(f"Dispatched Image Task to Pair #{pair.id} [{pair.name}] Queue")
                else:
                    logger.debug(f"Pair #{pair.id} [{pair.name}] is IMAGE mode, but received text-only message #{message.id}. Skipping.")

            elif pair.mode == PairMode.TEXT:
                if text_content and text_content.strip():
                    task = TaskMessage(
                        task_type=TaskType.TEXT_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        text=text_content,
                        reply_to_text=reply_context,
                        timestamp=time.time()
                    )
                    q.put(task)
                    logger.info(f"Dispatched Text Task to Pair #{pair.id} [{pair.name}] Queue")
                else:
                    logger.debug(f"Pair #{pair.id} [{pair.name}] is TEXT mode, but received image-only message #{message.id}. Skipping.")

            elif pair.mode == PairMode.BOTH:
                # If image exists, prioritize image task; else if text exists, dispatch text task
                if downloaded_image_path:
                    task = TaskMessage(
                        task_type=TaskType.IMAGE_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        image_path=downloaded_image_path,
                        caption=text_content,
                        timestamp=time.time()
                    )
                    q.put(task)
                    logger.info(f"Dispatched Image Task to Pair #{pair.id} [{pair.name}] Queue (BOTH mode)")
                elif text_content and text_content.strip():
                    task = TaskMessage(
                        task_type=TaskType.TEXT_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        text=text_content,
                        reply_to_text=reply_context,
                        timestamp=time.time()
                    )
                    q.put(task)
                    logger.info(f"Dispatched Text Task to Pair #{pair.id} [{pair.name}] Queue (BOTH mode)")
