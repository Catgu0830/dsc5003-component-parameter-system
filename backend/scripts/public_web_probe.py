"""Connectivity evidence only; example.com is not a component extraction accuracy test."""
import sys,json,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.sources import fetch_web
start=time.perf_counter()
try:
    content,url=fetch_web('https://example.com/')
    result={'passed':True,'url':url,'characters':len(content),'scope':'Public HTML and robots fetch only; not component extraction accuracy.'}
except Exception as exc:
    result={'passed':False,'error_type':type(exc).__name__,'error':str(exc)[:300],'scope':'Public network probe; no rules bypassed.'}
result['seconds']=round(time.perf_counter()-start,3)
(Path(__file__).resolve().parents[1]/'reports/public-web-probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
