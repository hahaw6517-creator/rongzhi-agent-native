"""Download untouched official annual reports; no financing execution."""
from pathlib import Path
import json,re,hashlib,concurrent.futures
import requests
import sys
sys.path.append(str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/Lib/site-packages'))
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tmp/official-cases';OUT.mkdir(exist_ok=True,parents=True)
SOURCES={
 'kingsoft-2025':'https://static.cninfo.com.cn/finalpage/2026-03-26/1225032227.PDF',
 'kingsoft-2024':'https://static.cninfo.com.cn/finalpage/2025-03-20/1222847501.PDF',
 'ninghu-2025':'https://static.cninfo.com.cn/finalpage/2026-03-30/1225049417.PDF',
 'ninghu-2024':'https://static.cninfo.com.cn/finalpage/2025-03-27/1222912237.PDF',
 'fuyao-2025':'https://static.cninfo.com.cn/finalpage/2026-03-18/1225014577.PDF',
 'fuyao-2024':'https://www.fuyaogroup.com/upfiles/investor/202503/1742298281488.pdf',
}
def discover():
 s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.cninfo.com.cn/'})
 identities=s.post('https://www.cninfo.com.cn/new/information/topSearch/query',data={'keyWord':'601888','maxNum':10},timeout=25).json()
 identity=next(x for x in identities if x.get('code')=='601888' and x.get('category')=='A股')
 body=s.post('https://www.cninfo.com.cn/new/hisAnnouncement/query',data=dict(pageNum=1,pageSize=100,column='sse',tabName='fulltext',stock='601888,'+identity['orgId'],searchkey='年度报告',seDate='2025-01-01~2026-10-15',isHLtitle='false'),timeout=25).json()
 for a in body.get('announcements',[]):
  title=re.sub('<[^>]+>','',a['announcementTitle'])
  if not any(x in title for x in ('摘要','英文','H股')):
   for y in (2024,2025):
    if str(y) in title and '年度报告' in title:SOURCES.setdefault(f'ctg-{y}','https://static.cninfo.com.cn/'+a['adjunctUrl'])
 assert all('ctg-'+str(y) in SOURCES for y in (2024,2025)),SOURCES
def fetch(pair):
 name,url=pair;pdf=OUT/(name+'.pdf')
 if not pdf.exists():
  r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=60);r.raise_for_status();assert r.content[:4]==b'%PDF';pdf.write_bytes(r.content)
 pages=[p.extract_text() or '' for p in PdfReader(pdf).pages]
 (OUT/(name+'.json')).write_text(json.dumps(pages,ensure_ascii=False),encoding='utf-8')
 return dict(name=name,url=url,pages=len(pages),sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
if __name__=='__main__':
 discover()
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(fetch,SOURCES.items()))
 (OUT/'sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 for r in results:print(json.dumps(r))
