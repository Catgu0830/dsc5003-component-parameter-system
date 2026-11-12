"""Reproducible corpus check through the production extraction entry point; no DB mutation."""
import argparse,json,sys,time,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.extraction import extract

def main():
    ap=argparse.ArgumentParser();ap.add_argument('root');ap.add_argument('--out',default='reports/pdf_verbatim');args=ap.parse_args()
    root=Path(args.root);out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    rows=[]
    for p in sorted(root.rglob('*.pdf')):
        start=time.monotonic();r={'file':str(p.relative_to(root))}
        try:
            digest=hashlib.sha256(p.read_bytes()).hexdigest()
            task={'source_type':'pdf','source_location':str(p),'source_sha256':digest,'original_filename':p.name,'input_json':'{}','component_id':None}
            result=extract(task,{'PDF_EXTRACTION_MODE':'verbatim'})
            specs=result['components'][0]['specifications']
            r.update(status='draft',candidates=len(specs),coverage=result['coverage'],sha256=digest)
            (out/(digest+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as exc:r.update(status='failed',error=getattr(exc,'message',str(exc)))
        r['seconds']=round(time.monotonic()-start,2);rows.append(r)
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(r,ensure_ascii=False),flush=True)
    summary={'files':len(rows),'nonempty_drafts':sum(x['status']=='draft' for x in rows),'at_least_5_candidates':sum(x.get('candidates',0)>=5 for x in rows),'note':'Candidate coverage only, not field accuracy or completeness.'}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(summary)
if __name__=='__main__':main()
