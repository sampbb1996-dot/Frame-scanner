# marketplace_field_scanner.py
import time, math, sqlite3, requests, re
from bs4 import BeautifulSoup
from dataclasses import dataclass

DB = "field.db"
POLL = 300
THRESH = 0.7
DECAY = 0.05
STEP = 0.08
COOLDOWN = 3600
HEADERS = {"User-Agent": "Mozilla/5.0"}

# ---------- model ----------

@dataclass
class Item:
    source: str
    id: str
    title: str
    price: float | None
    created_ts: float
    url: str

# ---------- utils ----------

def now(): return time.time()
def clamp(x,a,b): return max(a,min(b,x))
def sig(x): return 1/(1+math.exp(-x))

# ---------- db ----------

def db():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL;")
    return c

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS w(k TEXT PRIMARY KEY,v REAL,t REAL);
        CREATE TABLE IF NOT EXISTS cd(k TEXT PRIMARY KEY,u REAL);
        CREATE TABLE IF NOT EXISTS seen(s TEXT,i TEXT,PRIMARY KEY(s,i));
        """)

def weight(k):
    with db() as c:
        r = c.execute("SELECT v,t FROM w WHERE k=?", (k,)).fetchone()
        if not r: return 0.0
        v,t = r
        days = (now()-t)/86400
        return v*((1-DECAY)**max(days,0))

def cooldown(k):
    with db() as c:
        r = c.execute("SELECT u FROM cd WHERE k=?", (k,)).fetchone()
        return r and now()<r[0]

def seen(item):
    with db() as c:
        r = c.execute("SELECT 1 FROM seen WHERE s=? AND i=?", (item.source,item.id)).fetchone()
        if r: return True
        c.execute("INSERT INTO seen VALUES(?,?)", (item.source,item.id))
        return False

# ---------- field logic ----------

def keys(item):
    major = item.title.lower().split()[0] if item.title else "x"
    return {
        "src": f"s:{item.source}",
        "maj": f"m:{major}",
    }

def base_exc(item):
    b = 0.0
    if item.price is not None:
        b += clamp(1/(1+item.price),0,0.25)
    age_h = (now()-item.created_ts)/3600
    b += clamp(math.exp(-age_h/12)*0.25,0,0.25)
    return b

def excitation(item):
    x = base_exc(item)
    damp = 1.0
    for k in keys(item).values():
        if cooldown(k): damp *= 0.5
        x += clamp(weight(k), -0.35, 0.35)
    return clamp(sig(3*(x-0.35))*damp,0,1)

# ---------- scanners ----------

def scan_gumtree(url):
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.select("a[data-q='search-result-anchor']"):
        title = a.get_text(strip=True)
        href = "https://www.gumtree.com.au" + a["href"]
        price = None
        m = re.search(r"\$(\d+)", title)
        if m: price = float(m.group(1))
        items.append(Item(
            "gumtree",
            href.split("/")[-1],
            title,
            price,
            now(),
            href
        ))
    return items

def scan_fb(url):
    html = requests.get(url, headers=HEADERS, timeout=15).text
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for a in soup.find_all("a", href=True):
        if "/marketplace/item/" in a["href"]:
            title = a.get_text(strip=True)
            if not title: continue
            href = "https://www.facebook.com" + a["href"]
            items.append(Item(
                "fb",
                href.split("/")[-1],
                title,
                None,
                now(),
                href
            ))
    return items

# ---------- loop ----------

def run():
    init()
    GUMTREE_URL = "https://www.gumtree.com.au/s-all-results.html?sort=datedesc"
    FB_URL = "https://www.facebook.com/marketplace/"

    while True:
        for item in scan_gumtree(GUMTREE_URL) + scan_fb(FB_URL):
            if seen(item): continue
            exc = excitation(item)
            if exc >= THRESH:
                print(f"[NOTIFY] {item.source} exc={exc:.2f} {item.title}")
                print(item.url)
        time.sleep(POLL)

if __name__ == "__main__":
    run()
