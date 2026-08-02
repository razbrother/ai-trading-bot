from app.settings import settings
from app.models import Mode
class HealthService:
    def __init__(self,engine,opts):self.engine=engine;self.opts=opts
    async def snapshot(self):
        checks={'database':True,'telegram_user_lock':settings.telegram_allowed_user_id is not None,
          'market_source_real':self.opts.market_source=='groww','news_configured':self.opts.news_source!='none',
          'history_configured':self.opts.history_source!='none','gemini_key':bool(settings.gemini_api_key),
          'openai_key':bool(settings.openai_api_key),'groww_credentials':bool((settings.groww_totp_token and settings.groww_totp_secret) or (settings.groww_api_key and settings.groww_api_secret))}
        critical=['database'] if self.opts.mode==Mode.PAPER else ['database','telegram_user_lock','market_source_real','gemini_key','openai_key','groww_credentials']
        return {'checks':checks,'live_ready':all(checks[x] for x in critical)}
