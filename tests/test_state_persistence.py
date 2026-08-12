from app.settings import settings
from app.db import DB
from app.engine import Engine

def test_db_state_round_trip(tmp_path):
    db=DB(path=str(tmp_path/"s.db"))
    assert db.get_state("paused","False")=="False"
    db.set_state("paused","True")
    assert db.get_state("paused")=="True"
    db.set_state("paused","False")
    assert db.get_state("paused")=="False"

def test_engine_restores_persisted_pause_on_construction(tmp_path):
    db=DB(path=str(tmp_path/"s2.db"))
    db.set_state("paused","True");db.set_state("reason","reconcile mismatch")
    async def notify(t):pass
    engine=Engine(None,None,None,None,None,None,db,notify)
    assert engine.paused is True
    assert engine.reason=="reconcile mismatch"

def test_engine_defaults_to_unpaused_with_no_persisted_state(tmp_path):
    db=DB(path=str(tmp_path/"s3.db"))
    async def notify(t):pass
    engine=Engine(None,None,None,None,None,None,db,notify)
    assert engine.paused is False
    assert engine.reason==""

def test_setting_paused_persists_to_db(tmp_path):
    db=DB(path=str(tmp_path/"s4.db"))
    async def notify(t):pass
    engine=Engine(None,None,None,None,None,None,db,notify)
    engine.paused=True;engine.reason="manual emergency"
    assert db.get_state("paused")=="True"
    assert db.get_state("reason")=="manual emergency"

def test_auto_flag_is_never_persisted(tmp_path):
    db=DB(path=str(tmp_path/"s5.db"))
    async def notify(t):pass
    e1=Engine(None,None,None,None,None,None,db,notify)
    e1.auto=True
    assert db.get_state("auto") is None
    e2=Engine(None,None,None,None,None,None,db,notify)
    assert e2.auto==settings.auto_start
