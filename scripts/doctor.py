import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings
def p(n,v):print(f"[{'OK' if v else 'FAIL'}] {n}")
p("Telegram token",bool(settings.telegram_bot_token))
p("Telegram user lock",settings.telegram_allowed_user_id is not None)
p("Gemini key",bool(settings.gemini_api_key));p("OpenAI key",bool(settings.openai_api_key))
p("Groww credentials",bool((settings.groww_totp_token and settings.groww_totp_secret) or
 (settings.groww_api_key and settings.groww_api_secret)))
print("Mode:",settings.trading_mode.value,"Universe:",[x.symbol for x in settings.instruments])
