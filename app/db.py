import json, sqlite3
from pathlib import Path
from datetime import datetime, timezone
from app.settings import settings
from app.models import Position, BrokerOrder, Decision

SCHEMA="""
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts TEXT,kind TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,ts TEXT,provider TEXT,symbol TEXT,
 action TEXT,confidence REAL,payload TEXT);
CREATE TABLE IF NOT EXISTS orders(local_id TEXT PRIMARY KEY,broker_id TEXT,ts TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS positions(symbol TEXT PRIMARY KEY,ts TEXT,payload TEXT);
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,symbol TEXT,side TEXT,qty INTEGER,
 entry_time TEXT,exit_time TEXT,entry REAL,exit REAL,gross REAL,costs REAL,net REAL,reason TEXT);
"""
class DB:
    def __init__(self,path=None):
        self.path=path or settings.database_path
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        self._conn=sqlite3.connect(self.path)
        self._conn.row_factory=sqlite3.Row
        with self._conn:self._conn.executescript(SCHEMA)
    def conn(self):
        # A single connection reused for the DB object's lifetime. `with conn() as c`
        # only manages the transaction (commit/rollback), not the connection itself,
        # so this stays safe to call repeatedly without leaking file descriptors -
        # opening a fresh connection per call previously leaked one FD per call.
        return self._conn
    def event(self,k,p):
        with self.conn() as c:c.execute("INSERT INTO events(ts,kind,payload) VALUES(?,?,?)",
          (datetime.now(timezone.utc).isoformat(),k,json.dumps(p,default=str)))
    def decision(self,provider,d:Decision):
        with self.conn() as c:c.execute("""INSERT INTO decisions(ts,provider,symbol,action,confidence,payload)
          VALUES(?,?,?,?,?,?)""",(datetime.now(timezone.utc).isoformat(),provider,d.symbol,
          d.action.value,d.confidence,d.model_dump_json()))
    def order(self,o:BrokerOrder):
        with self.conn() as c:c.execute("""INSERT INTO orders(local_id,broker_id,ts,payload)
          VALUES(?,?,?,?) ON CONFLICT(local_id) DO UPDATE SET broker_id=excluded.broker_id,
          ts=excluded.ts,payload=excluded.payload""",(o.local_id,o.broker_id,o.updated_at.isoformat(),
          o.model_dump_json()))
    def save_pos(self,p:Position):
        with self.conn() as c:c.execute("""INSERT INTO positions(symbol,ts,payload) VALUES(?,?,?)
          ON CONFLICT(symbol) DO UPDATE SET ts=excluded.ts,payload=excluded.payload""",
          (p.symbol,datetime.now(timezone.utc).isoformat(),p.model_dump_json()))
    def positions(self):
        with self.conn() as c:r=c.execute("SELECT payload FROM positions").fetchall()
        return [Position.model_validate_json(x["payload"]) for x in r]
    def close(self,p:Position,exit_price,costs,reason):
        gross=((exit_price-p.avg_price) if p.side.value=="BUY" else (p.avg_price-exit_price))*p.qty
        net=gross-costs
        with self.conn() as c:
            c.execute("""INSERT INTO trades(symbol,side,qty,entry_time,exit_time,entry,exit,gross,costs,net,reason)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(p.symbol,p.side.value,p.qty,p.opened_at.isoformat(),
              datetime.now(timezone.utc).isoformat(),p.avg_price,exit_price,gross,costs,net,reason))
            c.execute("DELETE FROM positions WHERE symbol=?",(p.symbol,))
        return net
    def today(self,date):
        with self.conn() as c:r=c.execute("""SELECT COUNT(*) n,COALESCE(SUM(net),0) pnl FROM trades
          WHERE substr(exit_time,1,10)=?""",(date,)).fetchone()
        return int(r["n"]),float(r["pnl"])
    def report(self):
        with self.conn() as c:r=c.execute("SELECT net FROM trades ORDER BY exit_time").fetchall()
        p=[float(x["net"]) for x in r]; wins=[x for x in p if x>0]; losses=[x for x in p if x<0]
        eq=peak=dd=0
        for x in p:eq+=x;peak=max(peak,eq);dd=max(dd,peak-eq)
        return {"trades":len(p),"wins":len(wins),"losses":len(losses),
          "win_rate":len(wins)/len(p)*100 if p else 0,"net":sum(p),
          "profit_factor":sum(wins)/abs(sum(losses)) if losses else None,"max_drawdown":dd}
