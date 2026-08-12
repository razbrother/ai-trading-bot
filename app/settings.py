from datetime import time
from zoneinfo import ZoneInfo
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.models import Mode, Instrument

class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    trading_mode:Mode=Mode.PAPER; live_trading_unlock:bool=False; live_ack:str=""
    auto_start:bool=False; database_path:str="data/trading.db"; timezone:str="Asia/Kolkata"
    telegram_bot_token:str=""; telegram_allowed_user_id:int|None=None
    gemini_api_key:str=""; gemini_model:str="gemini-3.6-flash"
    openai_api_key:str=""; openai_model:str="gpt-5-mini"
    ai_min_confidence:float=Field(default=.8,ge=0,le=1)
    ai_first_trade_min_confidence:float=Field(default=.85,ge=0,le=1)
    ai_min_agreement_score:int=Field(default=85,ge=0,le=100)
    ai_max_entry_diff_pct:float=Field(default=.20,ge=0)
    ai_max_stop_diff_atr:float=Field(default=.30,ge=0)
    ai_max_target_diff_atr:float=Field(default=.50,ge=0)
    ai_require_consensus:bool=True
    groww_totp_token:str=""; groww_totp_secret:str=""
    groww_api_key:str=""; groww_api_secret:str=""
    symbols:str="RELIANCE:2885,TCS:11536,INFY:1594,SBIN:3045,ICICIBANK:4963"
    starting_capital:float=25000; max_risk_per_trade_pct:float=.005
    max_daily_loss:float=250; hard_daily_profit:float=400
    max_position_value:float=10000; max_open_positions:int=1; max_trades_per_day:int=2
    min_reward_risk:float=1.5; min_technical_score:int=75; max_spread_pct:float=.15
    max_signal_age_seconds:int=90; min_stop_atr_multiple:float=.5
    max_stop_atr_multiple:float=1.5
    entry_start:str="09:25"; last_entry:str="14:45"; force_exit:str="15:10"
    scan_interval_seconds:int=300; position_check_seconds:int=5
    reconcile_interval_seconds:int=30; paper_slippage_bps:float=5; paper_cost_bps:float=12
    live_cost_bps:float=20
    market_source:str="mock"; news_source:str="none"; history_source:str="none"
    require_news_for_entry:bool=False; require_history_for_entry:bool=True
    min_history_candles:int=100; max_news_age_minutes:int=60
    max_market_data_age_seconds:int=15; allow_mock_paper_only:bool=True
    top_candidates:int=5; app_version:str="2.0.0"; telegram_confirm_timeout_seconds:int=30
    require_live_health_pass:bool=True; require_telegram_user_lock_in_live:bool=True
    live_order_max_qty:int=1; live_probe_symbol:str="WIPRO"; live_probe_price:float=1
    live_probe_enable_order_test:bool=False; live_order_timeout_seconds:int=25
    live_order_poll_seconds:int=2; live_cancel_on_timeout:bool=True
    live_require_margin_check:bool=True; live_require_broker_stop:bool=True
    live_require_startup_reconciliation:bool=True
    single_instance_lock:str="/tmp/ai-trading-bot.lock"
    @property
    def tz(self): return ZoneInfo(self.timezone)
    def tm(self,s): h,m=map(int,s.split(":")); return time(h,m)
    @property
    def instruments(self):
        return [Instrument(symbol=s.split(":")[0],exchange_token=s.split(":")[1])
                for s in self.symbols.split(",")]
    def validate_live(self):
        if self.trading_mode==Mode.LIVE and not(
            self.live_trading_unlock and self.live_ack=="I_ACCEPT_REAL_MONEY_RISK"):
            raise RuntimeError("LIVE blocked: explicit unlock and acknowledgement required")

    gdelt_cache_seconds:int=300
    gdelt_min_request_interval_seconds:int=10
    gdelt_timespan:str="1h"
    gdelt_max_records:int=75
    gdelt_timeout_seconds:int=15
    news_terms:str="RELIANCE:Reliance Industries,TCS:Tata Consultancy Services,INFY:Infosys,SBIN:State Bank of India,ICICIBANK:ICICI Bank,WIPRO:Wipro"
    groww_order_rps:int=2
    groww_order_rpm:int=30
    groww_live_rps:int=6
    groww_live_rpm:int=180
    groww_nontrading_rps:int=8
    groww_nontrading_rpm:int=300
    openai_max_calls_per_day:int=30
    gemini_max_calls_per_day:int=30
    @property
    def news_term_map(self):
        out={}
        for item in self.news_terms.split(","):
            if ":" in item:
                symbol,term=item.split(":",1)
                out[symbol.strip().upper()]=term.strip()
        return out

settings=Settings()
