import os, json, hashlib, sqlite3, logging, urllib.request, datetime, time
import feedparser
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
DB=os.getenv('DB_PATH','news.db'); MAX_DAY=int(os.getenv('MAX_PER_DAY','3'))
TG_TOKEN=os.environ['TELEGRAM_BOT_TOKEN']; TG_CHANNEL=os.getenv('TELEGRAM_CHANNEL','@zavtrablize'); GEMINI_KEY=os.environ['GEMINI_API_KEY']; MODEL=os.getenv('GEMINI_MODEL','gemini-2.5-flash-lite')
RSS=['https://www.sciencedaily.com/rss/all.xml','https://www.nasa.gov/rss/dyn/breaking_news.rss','https://www.esa.int/rssfeed/Our_Activities/Space_Science','https://feeds.arstechnica.com/arstechnica/science','https://www.sciencedaily.com/rss/top/science.xml']
def db():
 c=sqlite3.connect(DB); c.execute('CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY,url TEXT,title TEXT,status TEXT,created TEXT,post TEXT,doc_url TEXT,error TEXT)'); c.commit(); return c
def req(url,data=None,headers=None):
 r=urllib.request.Request(url,data=data,headers=headers or {},method='POST' if data else 'GET')
 with urllib.request.urlopen(r,timeout=40) as x:return x.read()
def tg(text):
 p=json.dumps({'chat_id':TG_CHANNEL,'text':text,'disable_web_page_preview':False}).encode(); raw=req(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',p,{'Content-Type':'application/json'}); d=json.loads(raw)
 if not d.get('ok'): raise RuntimeError('Telegram API: '+str(d))
 return d['result']['message_id']
def digest(u):return hashlib.sha256(u.strip().encode()).hexdigest()
def generate(title,url,summary):
 prompt=f'''Ты редактор научно-технологического канала «Завтра ближе». Используй только переданные данные, не выдумывай детали и не представляй пресс-релиз как независимую проверку. Отсекай устаревшее (старше 14 дней), рекламное, слабое, неподтверждённое или повторное. Верни строго JSON: publish boolean, reason string, headline (до 100 символов), post (русский Telegram-пост 600-1300 символов, без кликбейта, с URL источника), article (статья 1500-3500 символов, с осторожными формулировками и источником). Заголовок: {title}\nURL: {url}\nОписание: {summary}'''
 b=json.dumps({'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':0.2,'responseMimeType':'application/json'}}).encode()
 d=json.loads(req(f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_KEY}',b,{'Content-Type':'application/json'})); return json.loads(d['candidates'][0]['content']['parts'][0]['text'])
def alert(msg):
 admin=os.getenv('TELEGRAM_ADMIN_ID')
 if admin:
  try:req(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',json.dumps({'chat_id':admin,'text':msg[:3500]}).encode(),{'Content-Type':'application/json'})
  except:logging.exception('Alert delivery failed')
def main():
 c=db(); today=datetime.datetime.now(datetime.timezone.utc).date().isoformat(); n=c.execute("SELECT COUNT(*) FROM articles WHERE status='published' AND created LIKE ?",(today+'%',)).fetchone()[0]
 if n>=MAX_DAY:logging.info('Daily cap reached');return
 candidates=[]; now=datetime.datetime.now(datetime.timezone.utc)
 for feed in RSS:
  try:
   f=feedparser.parse(feed)
   for e in f.entries[:15]:
    url=e.get('link','').strip(); title=e.get('title','').strip()
    if not url or not title or c.execute('SELECT 1 FROM articles WHERE id=?',(digest(url),)).fetchone():continue
    stamp=e.get('published_parsed') or e.get('updated_parsed')
    if stamp:
     dt=datetime.datetime(*stamp[:6],tzinfo=datetime.timezone.utc)
     if (now-dt).days>14 or dt>now+datetime.timedelta(hours=1):continue
     age=dt.timestamp()
    else: age=0
    candidates.append((age,digest(url),url,title,e.get('summary','')))
  except Exception:logging.exception('Feed error: %s',feed)
 candidates.sort(reverse=True)
 for _,uid,url,title,summary in candidates[:3]:
  created=now.isoformat(); c.execute('INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?,?,?)',(uid,url,title,'processing',created,None,None,None));c.commit()
  try:
   r=generate(title,url,summary)
   if not r.get('publish'):
    c.execute("UPDATE articles SET status='rejected',error=? WHERE id=?",(r.get('reason','filtered')[:500],uid));c.commit();continue
   post=r.get('post','').strip(); headline=r.get('headline','').strip(); article=r.get('article','').strip()
   if not post or not headline or not article or len(post)>3900:raise ValueError('Generated content invalid or too long')
   if url not in post:post+='\n\nИсточник: '+url
   # Mark ready before send; successful post ID is recorded immediately after delivery.
   c.execute("UPDATE articles SET status='ready',post=? WHERE id=?",(post,uid));c.commit()
   result=tg(post); message_id=result
   c.execute("UPDATE articles SET status='published',error=? WHERE id=?",('telegram_message_id='+str(message_id),uid));c.commit();n+=1
   logging.info('Published %s',headline)
   if n>=MAX_DAY:break
  except Exception as ex:
   c.execute("UPDATE articles SET status='error',error=? WHERE id=?",(str(ex)[:1000],uid));c.commit();logging.exception('Processing failure');alert('⚠️ «Завтра ближе»: ошибка публикации/обработки\n'+title+'\n'+str(ex))
if __name__=='__main__':main()
