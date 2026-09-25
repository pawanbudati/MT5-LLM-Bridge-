import os
import time
import datetime
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any, Set
from telethon import TelegramClient, events, utils as telethon_utils
from telethon.tl import types as telethon_types
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
        # Mapping pair_id -> resolved Telethon entity
        self.pair_entities: Dict[int, Any] = {}
        # Track dispatched message IDs per pair to avoid duplicate processing
        self.dispatched_msg_ids: Dict[int, Set[int]] = {p.id: set() for p in self.pairs}

    async def start(self):
        """Authenticate with Telegram, resolve all target channels, fetch past messages if configured, and register live event handler."""
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

        # 1. Fetch and process past messages for configured pairs before starting live listening
        await self._fetch_and_process_past_messages()

        # 2. Register unified live new message & edited message event handlers
        # Handlers are registered without chats filter so Telethon never drops updates due to peer ID discrepancies.
        # Routing and channel matching are handled reliably in _handle_incoming_event.
        @self.client.on(events.NewMessage())
        async def on_new_message(event):
            await self._handle_incoming_event(event, is_edit=False)

        @self.client.on(events.MessageEdited())
        async def on_message_edited(event):
            await self._handle_incoming_event(event, is_edit=True)

        logger.info(Fore.GREEN + Style.BRIGHT + "\n" + "=" * 70)
        logger.info(f" [*] MASTER TELEGRAM LISTENER ACTIVE - LISTENING TO {len(self.subscribed_entities)} CHANNELS")
        for p in self.pairs:
            past_info = f"Past Messages: {p.past_hours:g}h" if p.past_hours > 0 else "Past Messages: Disabled"
            logger.info(f"     Pair #{p.id} [{p.name}]: Channel '{p.channel}' -> Mode: {p.mode.value.upper()} | {past_info}")
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
                # Store entity for pair
                self.pair_entities[pair.id] = entity

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

    async def _fetch_and_process_past_messages(self):
        """
        For each configured pair where past_hours > 0, retrieve past messages
        from its channel in chronological order and dispatch to its worker queue.
        """
        pairs_with_past = [p for p in self.pairs if getattr(p, "past_hours", 0) and p.past_hours > 0]
        if not pairs_with_past:
            logger.info("Past messages retrieval: Disabled (all pairs configured with 0 or blank past_hours).")
            return

        logger.info(Fore.CYAN + Style.BRIGHT + "\n" + "=" * 70)
        logger.info(" [*] RETRIEVING PAST MESSAGES FOR CONFIGURED PAIRS ON STARTUP")
        logger.info("=" * 70 + Style.RESET_ALL)

        for pair in pairs_with_past:
            entity = self.pair_entities.get(pair.id)
            if not entity:
                logger.warning(f"[-] Cannot retrieve past messages for Pair #{pair.id} [{pair.name}]: Channel '{pair.channel}' was not resolved.")
                continue

            past_hours = pair.past_hours
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            cutoff_time = now_utc - datetime.timedelta(hours=past_hours)

            logger.info(
                f"[*] Pair #{pair.id} [{pair.name}]: Fetching messages from past {past_hours:g} hour(s) "
                f"(Since: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S UTC')})..."
            )

            past_messages = []
            try:
                async for msg in self.client.iter_messages(entity, limit=1000):
                    if isinstance(msg, telethon_types.MessageService):
                        continue

                    msg_date = getattr(msg, "date", None)
                    if msg_date:
                        if msg_date.tzinfo is None:
                            msg_date = msg_date.replace(tzinfo=datetime.timezone.utc)
                        if msg_date < cutoff_time:
                            break
                    past_messages.append(msg)
            except Exception as e:
                logger.error(f"Error retrieving past messages for Pair #{pair.id} [{pair.name}]: {e}", exc_info=True)
                continue

            if not past_messages:
                logger.info(f"    No messages found in the last {past_hours:g} hour(s) for Pair #{pair.id} [{pair.name}].")
                continue

            # iter_messages yields newest to oldest. Reverse to process chronologically (oldest -> newest).
            past_messages.reverse()
            logger.info(
                Fore.GREEN +
                f"[+] Pair #{pair.id} [{pair.name}]: Retrieved {len(past_messages)} past messages "
                f"(Msg #{past_messages[0].id} to #{past_messages[-1].id}). Dispatching in chronological order..." +
                Style.RESET_ALL
            )

            for msg in past_messages:
                await self._dispatch_message(msg, matching_pairs=[pair], is_past=True)

            logger.info(Fore.GREEN + f"[+] Pair #{pair.id} [{pair.name}]: All {len(past_messages)} past messages dispatched to queue.\n" + Style.RESET_ALL)

        logger.info(Fore.CYAN + " [*] Finished retrieving past messages. Transitioning to live listening...\n" + Style.RESET_ALL)

    async def _handle_incoming_event(self, event, is_edit: bool = False):
        """Route incoming live or edited message to subscribed pair queues."""
        message = getattr(event, 'message', None)
        if not message:
            return

        chat_id = getattr(event, 'chat_id', None)
        if chat_id is None and hasattr(message, 'peer_id'):
            try:
                chat_id = telethon_utils.get_peer_id(message.peer_id)
            except Exception:
                chat_id = None

        if chat_id is None:
            return

        str_chat_id = str(chat_id)
        raw_id_str = str_chat_id.replace("-100", "").lstrip("-")

        # Collect candidate lookup keys from event
        lookup_keys = {str_chat_id, raw_id_str, f"-100{raw_id_str}", f"-{raw_id_str}"}

        chat = getattr(event, 'chat', None)
        if chat:
            uname = getattr(chat, 'username', None)
            if uname:
                lookup_keys.add(uname.lower())
                lookup_keys.add(f"@{uname.lower()}")
            title = getattr(chat, 'title', None)
            if title:
                lookup_keys.add(title.lower())

        # Match against channel_pairs_map
        matching_pairs: List[PairConfig] = []
        for k in lookup_keys:
            if k in self.channel_pairs_map:
                for p in self.channel_pairs_map[k]:
                    if p not in matching_pairs:
                        matching_pairs.append(p)

        # Fallback check against configured pair channels directly
        if not matching_pairs:
            for p in self.pairs:
                c_clean = p.channel.strip().lower()
                c_bare = c_clean.lstrip("@").replace("-100", "").lstrip("-")
                if (c_clean in lookup_keys or 
                    c_bare in lookup_keys or 
                    p.channel.strip() in lookup_keys):
                    if p not in matching_pairs:
                        matching_pairs.append(p)

        if not matching_pairs:
            return

        edit_tag = "[LIVE-EDIT]" if is_edit else "[LIVE]"
        chat_name = getattr(chat, 'title', '') or getattr(chat, 'username', '') or str_chat_id
        logger.info(
            Fore.CYAN + 
            f"{edit_tag} Event in '{chat_name}' (Chat ID: {str_chat_id} | Msg #{message.id}) -> Matched {len(matching_pairs)} Pair(s)" + 
            Style.RESET_ALL
        )

        await self._dispatch_message(
            message,
            matching_pairs=matching_pairs,
            chat_id=chat_id,
            is_past=False,
            is_edit=is_edit
        )

    async def _dispatch_message(
        self,
        message: Any,
        matching_pairs: List[PairConfig],
        chat_id: Optional[Any] = None,
        is_past: bool = False,
        is_edit: bool = False
    ):
        """Extract media/text from a message and dispatch TaskMessage to matching pair queues."""
        if chat_id is None:
            chat_id = getattr(message, 'chat_id', None)
            if chat_id is None and hasattr(message, 'peer_id'):
                try:
                    chat_id = telethon_utils.get_peer_id(message.peer_id)
                except Exception:
                    chat_id = None
        str_chat_id = str(chat_id or "")

        # Filter out pairs that have already dispatched this message ID (allow reprocessing if edited)
        eligible_pairs: List[PairConfig] = []
        for p in matching_pairs:
            pair_dispatched = self.dispatched_msg_ids.setdefault(p.id, set())
            if not is_edit and message.id in pair_dispatched:
                logger.debug(f"Message #{message.id} already processed for Pair #{p.id} [{p.name}]. Skipping duplicate.")
            else:
                eligible_pairs.append(p)

        if not eligible_pairs:
            return

        has_photo = bool(getattr(message, "photo", None))
        has_image_doc = bool(
            getattr(message, "document", None) and 
            message.document.mime_type and 
            message.document.mime_type.startswith("image/")
        )
        is_image_msg = has_photo or has_image_doc
        text_content = getattr(message, "message", "") or ""

        # Download image once if any eligible pair requires an image
        downloaded_image_path = None
        needs_image = any(p.mode in (PairMode.IMAGE, PairMode.BOTH) for p in eligible_pairs)
        if is_image_msg and needs_image:
            file_ext = ".jpg"
            if has_image_doc and message.document.mime_type:
                ext = message.document.mime_type.split("/")[-1]
                if ext in ("png", "jpeg", "webp"):
                    file_ext = f".{ext}"

            # Check if file already exists in downloads
            existing_files = list(settings.DOWNLOADS_DIR.glob(f"chart_msg_{message.id}_*{file_ext}"))
            if existing_files and existing_files[0].exists() and existing_files[0].stat().st_size > 0:
                downloaded_image_path = str(existing_files[0])
            else:
                save_path = settings.DOWNLOADS_DIR / f"chart_msg_{message.id}_{int(time.time())}{file_ext}"
                try:
                    tag = "[PAST]" if is_past else ("[LIVE-EDIT]" if is_edit else "[LIVE]")
                    logger.info(f"{tag} Downloading image media from chat {chat_id} (Msg #{message.id})...")
                    downloaded = await asyncio.wait_for(
                        message.download_media(file=str(save_path)),
                        timeout=30.0
                    )
                    if downloaded:
                        downloaded_image_path = str(save_path)
                except asyncio.TimeoutError:
                    logger.error(f"Image download timed out after 30s for Msg #{message.id}")
                except Exception as e:
                    logger.error(f"Error downloading image media: {e}")

        # Fetch reply context if message is reply and text is needed
        reply_context = None
        needs_text = any(p.mode in (PairMode.TEXT, PairMode.BOTH) for p in eligible_pairs)
        is_reply = getattr(message, "is_reply", False)
        if callable(is_reply):
            try:
                is_reply = is_reply()
            except Exception:
                is_reply = False

        if is_reply and needs_text and hasattr(message, "get_reply_message"):
            try:
                reply_msg = await message.get_reply_message()
                if reply_msg and getattr(reply_msg, "raw_text", None):
                    reply_context = reply_msg.raw_text
            except Exception as e:
                logger.warning(f"Could not fetch reply context: {e}")

        # Extract message timestamp
        msg_date = getattr(message, "date", None)
        if msg_date:
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=datetime.timezone.utc)
            timestamp = msg_date.timestamp()
            date_display = msg_date.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            timestamp = time.time()
            date_display = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))

        tag = "[PAST]" if is_past else ("[LIVE-EDIT]" if is_edit else "[LIVE]")

        # Dispatch to respective pairs
        for pair in eligible_pairs:
            q = self.pair_queues.get(pair.id)
            if not q:
                continue

            task: Optional[TaskMessage] = None

            if pair.mode == PairMode.IMAGE:
                if downloaded_image_path:
                    task = TaskMessage(
                        task_type=TaskType.IMAGE_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        image_path=downloaded_image_path,
                        caption=text_content,
                        timestamp=timestamp
                    )
                elif text_content and text_content.strip():
                    task = TaskMessage(
                        task_type=TaskType.TEXT_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        text=text_content,
                        reply_to_text=reply_context,
                        timestamp=timestamp
                    )
                else:
                    logger.info(f"{tag} Pair #{pair.id} [{pair.name}] Msg #{message.id} has no image and no text content. Skipping.")

            elif pair.mode == PairMode.TEXT:
                if text_content and text_content.strip():
                    task = TaskMessage(
                        task_type=TaskType.TEXT_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        text=text_content,
                        reply_to_text=reply_context,
                        timestamp=timestamp
                    )
                elif downloaded_image_path:
                    task = TaskMessage(
                        task_type=TaskType.IMAGE_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        image_path=downloaded_image_path,
                        caption=text_content,
                        timestamp=timestamp
                    )
                else:
                    logger.info(f"{tag} Pair #{pair.id} [{pair.name}] Msg #{message.id} has no text and no image. Skipping.")

            elif pair.mode == PairMode.BOTH:
                if downloaded_image_path:
                    task = TaskMessage(
                        task_type=TaskType.IMAGE_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        image_path=downloaded_image_path,
                        caption=text_content,
                        timestamp=timestamp
                    )
                elif text_content and text_content.strip():
                    task = TaskMessage(
                        task_type=TaskType.TEXT_TASK,
                        pair_id=pair.id,
                        channel_id=str_chat_id,
                        message_id=message.id,
                        text=text_content,
                        reply_to_text=reply_context,
                        timestamp=timestamp
                    )
                else:
                    logger.info(f"{tag} Pair #{pair.id} [{pair.name}] Msg #{message.id} has no image and no text. Skipping.")

            if task:
                q.put(task)
                self.dispatched_msg_ids[pair.id].add(message.id)
                logger.info(
                    Fore.GREEN + 
                    f"{tag} Dispatched {task.task_type.value.upper()} Task (Msg #{message.id} | {date_display}) "
                    f"to Pair #{pair.id} [{pair.name}] Queue" + 
                    Style.RESET_ALL
                )
