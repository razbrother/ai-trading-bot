import os,fcntl
class SingletonLock:
    def __init__(self,path):self.path=path;self.fd=None
    def acquire(self):
        self.fd=os.open(self.path,os.O_CREAT|os.O_RDWR,0o600)
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError("Another bot instance is running")
        os.ftruncate(self.fd,0);os.write(self.fd,str(os.getpid()).encode())
    def release(self):
        if self.fd is not None:fcntl.flock(self.fd,fcntl.LOCK_UN);os.close(self.fd);self.fd=None
