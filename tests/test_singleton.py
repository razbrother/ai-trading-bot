import pytest
from app.singleton import SingletonLock

def test_second_acquire_fails_while_first_holds_lock(tmp_path):
    path=str(tmp_path/"bot.lock")
    a=SingletonLock(path);a.acquire()
    b=SingletonLock(path)
    with pytest.raises(RuntimeError):
        b.acquire()
    a.release()

def test_acquire_succeeds_again_after_release(tmp_path):
    path=str(tmp_path/"bot.lock")
    a=SingletonLock(path);a.acquire();a.release()
    b=SingletonLock(path)
    b.acquire()
    b.release()
