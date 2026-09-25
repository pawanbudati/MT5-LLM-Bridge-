import re
import logging
from colorama import Fore, Style

class ColoredFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: Style.DIM + Fore.WHITE,
        logging.INFO: Fore.CYAN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.RED + Style.BRIGHT,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, Fore.WHITE)
        msg = super().format(record)
        return f"{color}{msg}{Style.RESET_ALL}"

def is_scrap_message(text: str) -> bool:
    """
    Detect non-trading messages: chatter, pips bragging, celebration, social links, feedback requests.
    """
    if not text:
        return True

    clean = re.sub(r'[*_`#]', '', text).upper().strip()

    # 1. URLs and Links
    if any(k in clean for k in ["HTTP://", "HTTPS://", "INSTAGRAM.COM", "T.ME/", "YOUTUBE.COM", "YOUTU.BE"]):
        return True

    # 2. Pips bragging / running updates (e.g. "200 PIPS RUNNING", "300 PIPS DONE")
    if "PIPS" in clean and any(w in clean for w in ["RUNNING", "BOOKED", "HIT", "DONE", "GAINED", "PROFIT", "ENJOY"]):
        return True

    # 3. Target hit celebrations without new signal (e.g. "2ND TGT HIT", "TP1 HIT", "ALL TARGETS HIT")
    if any(w in clean for w in [
        "TGT HIT", "TARGET HIT", "TP HIT", "TARGETS HIT", 
        "TGT REACHED", "TARGET REACHED", "ALL TP DONE", 
        "BOOM", "CONGRATULATIONS", "CONGRATS"
    ]):
        if not any(k in clean for k in ["BUY", "SELL", "MOVE SL", "SL TO", "NEW TP", "ENTRY"]):
            return True

    # 4. Social media, feedback, and promotional chatter
    scrap_keywords = [
        "INSTA", "INSTAGRAM", "VIDEO", "YOUTUBE", "REEL",
        "COMMENTS", "COMMENT", "EXPERIENCE", "EXPERIANCE", "FEEDBACK",
        "JOIN VIP", "VIP CHANNEL", "ADMIN", "WHATSAPP", "CONTACT",
        "SUBSCRIBE", "LIKE AND SHARE", "REGISTER", "DISCLAIMER",
        "GOOD MORNING", "GOOD NIGHT", "HAPPY WEEKEND"
    ]
    if any(k in clean for k in scrap_keywords):
        if not any(k in clean for k in ["BUY", "SELL", "SL ", "SL-", "SL:"]):
            return True

    return False

def clean_channel_id(ch: str) -> str:
    """Standardize channel representation."""
    if not ch:
        return ""
    c = str(ch).strip()
    return c
