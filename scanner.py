import os,time,json,re,hashlib,requests,feedparser
from datetime import datetime,timezone,timedelta

POLL=180
MAX_ALERTS=8
COOLDOWN=900
STATE="state.json"

ANCHORS={
"dining chair":80,
"office chair":120,
"timber table":250
}

BANNED=("broken","faulty","parts","repair","spares")

PRICE_RE=re.compile(r"(\$|AUD\s*)([0-9][0-9,]*)")

def now():return datetime.now(timezone.utc)
def today():return now().date().isoformat()

def load():
    if not os.path.exists(STATE):
        return {"seen":{}, "day":today(), "sent":0, "cool":0}
    return json.load(open(STATE))

def save(s):
    json.dump(s,open(STATE,"w"))

def price(t):
    m=PRICE_RE.search(t or "")
    return float(m.group(2).replace(",","")) if m else None

def uid(t,l):
    return hashlib.sha1((t+l).encode()).hexdigest()

def under(p,a):
    return (a-p)>=40 or ((a-p)/a)>=0.35

def rss_urls():
    env=os.getenv("FASTCASH_RSS_URLS","")
    return [u for u in env.splitlines() if u.strip()]

def notify(msg):
    tok=os.getenv("FASTCASH_TELEGRAM_TOKEN")
    cid=os.getenv("FASTCASH_TELEGRAM_CHAT_ID")
    if tok and cid:
        requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id":cid,"text":msg},
            timeout=10
        )

def scan(e,s):
    t=(e.get("title","")+e.get("summary","")).lower()
    if any(b in t for b in BANNED):return
    p=price(t)
    if not p or p<25 or p>900:return
    k=next((k for k in ANCHORS if k in t),None)
    if not k:return
    if not under(p,ANCHORS[k]):return
    if s["sent"]>=MAX_ALERTS or time.time()<s["cool"]:return
    notify(f"{k} ${p}\n{e.get('link','')}")
    s["sent"]+=1
    s["cool"]=time.time()+COOLDOWN

def main():
    s=load()
    if s["day"]!=today():
        s["day"]=today()
        s["sent"]=0
    urls=rss_urls()
    while True:
        for u in urls:
            try:
                f=feedparser.parse(requests.get(u,timeout=10).content)
                for e in f.entries:
                    i=uid(e.get("title",""),e.get("link",""))
                    if i in s["seen"]:continue
                    s["seen"][i]=1
                    scan(e,s)
            except:pass
        if len(s["seen"])>4000:
            for k in list(s["seen"])[:1000]:
                del s["seen"][k]
        save(s)
        time.sleep(POLL)

main()
