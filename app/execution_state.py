from enum import Enum
from pydantic import BaseModel
from datetime import datetime
class ExecutionState(str,Enum):
    INTENT_SAVED="INTENT_SAVED";SUBMITTED="SUBMITTED";ACKED="ACKED";OPEN="OPEN"
    PARTIAL="PARTIAL";FILLED="FILLED";CANCEL_REQUESTED="CANCEL_REQUESTED"
    CANCELLED="CANCELLED";REJECTED="REJECTED";FAILED="FAILED";UNKNOWN="UNKNOWN"
    POSITION_CONFIRMED="POSITION_CONFIRMED";PROTECTION_SUBMITTED="PROTECTION_SUBMITTED"
    PROTECTED="PROTECTED";EXIT_SUBMITTED="EXIT_SUBMITTED";CLOSED="CLOSED"
class ExecutionRecord(BaseModel):
    reference_id:str;symbol:str;side:str;requested_qty:int;filled_qty:int=0
    broker_order_id:str|None=None;state:ExecutionState=ExecutionState.INTENT_SAVED
    average_price:float|None=None;remark:str="";updated_at:datetime
