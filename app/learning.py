from app.db import DB
class PreviousTradeAnalyzer:
    def __init__(self,db:DB): self.db=db
    def evidence(self,symbol):
        with self.db.conn() as c: rows=c.execute("SELECT net FROM trades WHERE symbol=? ORDER BY exit_time DESC LIMIT 100",(symbol,)).fetchall()
        p=[float(x['net']) for x in rows];w=[x for x in p if x>0]
        return {'symbol':symbol,'sample_size':len(p),'observed_win_rate':len(w)/len(p) if p else None,
          'average_net_pnl':sum(p)/len(p) if p else None,'warning':'Own completed trades only; not a calibrated probability'}
