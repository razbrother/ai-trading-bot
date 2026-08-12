import time
from app.telegram_console import Confirmations

def test_confirm_via_slash_command_form():
    c=Confirmations()
    code=c.create(1,"START")
    # This is the only form a real Telegram CommandHandler can ever deliver:
    # /confirm <code> -> context.args=["<code>"] -> " ".join(...) == "<code>".
    assert c.consume(1,code)=="START"

def test_confirm_also_accepts_confirm_prefixed_form():
    c=Confirmations()
    code=c.create(1,"START")
    assert c.consume(1,f"CONFIRM {code}")=="START"

def test_confirm_is_case_insensitive():
    c=Confirmations()
    code=c.create(1,"START")
    assert c.consume(1,f"confirm {code}")=="START"

def test_wrong_code_rejected():
    c=Confirmations()
    c.create(1,"START")
    assert c.consume(1,"0000") is None

def test_code_is_single_use():
    c=Confirmations()
    code=c.create(1,"START")
    assert c.consume(1,code)=="START"
    assert c.consume(1,code) is None

def test_expired_code_rejected(monkeypatch):
    c=Confirmations()
    code=c.create(1,"START")
    c.p[1]=(c.p[1][0],c.p[1][1],time.time()-9999)
    assert c.consume(1,code) is None

def test_different_user_cannot_consume_others_code():
    c=Confirmations()
    code=c.create(1,"START")
    assert c.consume(2,code) is None
