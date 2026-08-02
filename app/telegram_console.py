import secrets,time
from app.settings import settings
class Confirmations:
    def __init__(self):self.p={}
    def create(self,uid,action):
        code=str(secrets.randbelow(9000)+1000);self.p[uid]=(action,code,time.time());return code
    def consume(self,uid,text):
        x=self.p.get(uid)
        if not x:return None
        action,code,t=x
        if time.time()-t>settings.telegram_confirm_timeout_seconds:self.p.pop(uid,None);return None
        if text.strip().upper()==f'CONFIRM {code}':self.p.pop(uid,None);return action
        return None

def settings_text(opts):
    vals={'version':settings.app_version,'mode':opts.mode.value,'market':opts.market_source,'news':opts.news_source,
    'history':opts.history_source,'capital':settings.starting_capital,'risk_pct':settings.max_risk_per_trade_pct,
    'daily_loss':settings.max_daily_loss,'profit_stop':settings.hard_daily_profit,'max_trades':settings.max_trades_per_day,
    'min_rr':settings.min_reward_risk,'first_conf':settings.ai_first_trade_min_confidence,
    'later_conf':settings.ai_min_confidence,'agreement':settings.ai_min_agreement_score,'top_candidates':settings.top_candidates,
    'symbols':[x.symbol for x in settings.instruments]}
    return '\n'.join(f'{k}: {v}' for k,v in vals.items())
