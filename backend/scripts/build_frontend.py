"""Build shared API/viewer bundle and validate every frontend page's local assets."""
import re,json,hashlib,subprocess
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[2]/'frontend'
marker='// Shared specification UI is bundled here'
p=ROOT/'js/api.js';core=p.read_text(encoding='utf-8').split(marker)[0].rstrip();p.write_text(core+'\n\n'+marker+' so every API-enabled page has it.\n'+(ROOT/'js/specifications.js').read_text(encoding='utf-8'),encoding='utf-8')
assets=list((ROOT/'js').glob('*.js'))+list((ROOT/'css').glob('*.css'))
version=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(assets))).hexdigest()[:12]
class Check(HTMLParser):
 def __init__(self):super().__init__();self.ids=[];self.links=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if 'id' in a:self.ids.append(a['id'])
  if tag in ('script','link'):self.links.append(a.get('src',a.get('href','')))
pages=[ROOT/'login.html',*list((ROOT/'pages').glob('*.html'))]
for p in pages:
 s=p.read_text(encoding='utf-8');s=re.sub(r'((?:src|href)="(?:\.\./)?(?:js|css)/[^"?]+\.(?:js|css))(?:\?[^" ]*)?"',lambda m:m[1]+'?v='+version+'"',s);p.write_text(s,encoding='utf-8')
 check=Check();check.feed(s);assert len(check.ids)==len(set(check.ids)),str(p)+' has duplicate IDs'
 for link in check.links:
  if not link or link.startswith(('http:','https:')):continue
  assert (p.parent/link.split('?')[0]).exists(),str(p)+' missing '+link
for p in (ROOT/'js').glob('*.js'):subprocess.run(['node','--check',str(p)],check=True)
(ROOT/'build-manifest.json').write_text(json.dumps({'version':version,'pages':[str(p.relative_to(ROOT)) for p in pages],'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}},indent=2),encoding='utf-8')
print('Validated',len(pages),'pages;',len(assets),'assets; build',version)
