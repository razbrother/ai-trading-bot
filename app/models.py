from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Mode(str, Enum):
    PAPER="PAPER"; LIVE="LIVE"
class Action(str, Enum):
    BUY="BUY"; SELL="SELL"; HOLD="HOLD"; EXIT="EXIT"
class Status(str, Enum):
    SUBMITTED="SUBMITTED"; OPEN="OPEN"; PARTIAL="PARTIAL"; FILLED="FILLED"
    REJECTED="REJECTED"; CANCELLED="CANCELLED"; UNKNOWN="UNKNOWN"

class Instrument(BaseModel):
    symbol:str; exchange_token:str; exchange:str="NSE"; segment:str="CASH"

class Snapshot(BaseModel):
    symbol:str; timestamp:datetime; ltp:float=Field(gt=0); open:float=Field(gt=0)
    high:float=Field(gt=0); low:float=Field(gt=0); volume_ratio:float=Field(ge=0)
    bid:float|None=None; ask:float|None=None; vwap:float=Field(gt=0)
    ema9:float=Field(gt=0); ema21:float=Field(gt=0); rsi:float=Field(ge=0,le=100)
    atr:float=Field(gt=0); index_change:float=0; sector_change:float=0
    news_risk:Literal["LOW","MEDIUM","HIGH","UNKNOWN"]="UNKNOWN"; source:str="unknown"
    @property
    def spread_pct(self):
        return ((self.ask-self.bid)/self.ltp*100) if self.bid and self.ask else 0.0

class Candidate(BaseModel):
    snapshot:Snapshot; score:int=Field(ge=0,le=100); reasons:list[str]=[]

class Decision(BaseModel):
    action:Action; symbol:str; entry:float|None=Field(default=None,gt=0)
    stop:float|None=Field(default=None,gt=0); target:float|None=Field(default=None,gt=0)
    confidence:float=Field(ge=0,le=1); hold_minutes:int=Field(default=30,ge=1,le=360)
    reasons:list[str]=[]; rationale:str=""
    @model_validator(mode="after")
    def check(self):
        if self.action in {Action.BUY,Action.SELL} and None in (self.entry,self.stop,self.target):
            raise ValueError("trade prices required")
        return self

class Review(BaseModel):
    approved:bool; action:Action; confidence:float=Field(ge=0,le=1)
    concerns:list[str]=[]; rationale:str=""

class ValidOrder(BaseModel):
    symbol:str; action:Action; qty:int=Field(gt=0); entry:float=Field(gt=0)
    stop:float=Field(gt=0); target:float=Field(gt=0); risk:float=Field(gt=0)
    rr:float=Field(gt=0); confidence:float=Field(ge=0,le=1); score:int
    signal_time:datetime

class BrokerOrder(BaseModel):
    local_id:str; broker_id:str|None=None; symbol:str; action:Action; qty:int
    filled_qty:int=0; requested_price:float; avg_price:float|None=None
    status:Status; message:str=""; updated_at:datetime

class Position(BaseModel):
    symbol:str; qty:int; side:Action; avg_price:float; stop:float; target:float
    opened_at:datetime; broker_id:str|None=None; ltp:float|None=None; upnl:float=0
    stop_order_id:str|None=None
