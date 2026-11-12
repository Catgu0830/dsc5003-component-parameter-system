"""Evidence-first extraction. No scalar coercion or inferred electrical semantics."""
import re
from pathlib import Path
from .common import APIError

TOPIC = re.compile(r'\b(?:voltage|current|frequency|clock|memory|flash|sram|ram|temperature|resolution|bandwidth|gain|noise|accuracy|supply|power|package|channels?|sampling|sample rate|conversion|input|output|interface|ethernet|data rate|transfer rates?|poe|humidity|ports?|operating|quiescent|standby|shutdown|offset|slew|capacitance|resistance)\b', re.I)
VALUE = re.compile(r'(?<![A-Za-z])[±+−-]?\d+(?:\.\d+)?\s*(?:(?:to|[-–~])\s*[±+−-]?\d+(?:\.\d+)?\s*)?(?:[pnumkMGµμ]?V|[pnumkµμ]?A|[kMG]?Hz|[mµμ]?s|[mµμ]?W|[kKM]?bytes?|[kKM]?bits?|[kKM]?B|[°⁰]\s*[CF]|bits?|dB|ppm|%|[kM]?SPS|[kM]?bps|[pnumµμ]?F|Ω)(?![A-Za-z])', re.I)
PACKAGE = re.compile(r'\b(?:LQFP|QFN|SOIC|MSOP|TSSOP|BGA|WLCSP|UFBGA|VFQFPN|UFQFPN|SOT)[- ]?\d*\b', re.I)
EXCLUDE = re.compile(r'\b(?:figure\s+\d|table of contents|list of tables|revision history|document revision|copyright|ordering information)\b',re.I)
MFR = [('analog.com','Analog Devices'),('analog devices','Analog Devices'),('espressif','Espressif Systems'),('gigadevice','GigaDevice'),('microchip','Microchip Technology'),('st.com','STMicroelectronics'),('stmicroelectronics','STMicroelectronics')]
MODEL = re.compile(r'\b(?:STM32[A-Z0-9xX-]+|GD32[A-Z0-9xX-]+|ESP(?:32|82|86)[A-Z0-9_-]*|AD(?:[A-Z]{0,4})\d[A-Z0-9/-]*|MCP\d[A-Z0-9/-]*|MIC\d[A-Z0-9/-]*|PIC\d[A-Z0-9/-]*|(?:PDS?|HV|USB|USX|ZL|CN|MX)[-]?\d[A-Z0-9/-]*)\b',re.I)


def page_lines(page):
    """Keep each actual PDF line and its coordinates, rather than inventing table cells."""
    result=[]
    for block in page.get_text('dict',flags=__import__('pymupdf').TEXTFLAGS_DICT & ~__import__('pymupdf').TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            s=''.join(span['text'] for span in line['spans']).strip()
            if s: result.append((s,list(line['bbox'])))
    return result


def table_excerpts(lines, page_no):
    # Group co-linear PDF text fragments. Only operate below a visible numeric table header.
    rows=[]
    for text,box in sorted(lines,key=lambda x:(round(x[1][1]/3),x[1][0])):
        if rows and abs(rows[-1][0][1][1]-box[1])<3:
            rows[-1].append((text,box))
        else: rows.append([(text,box)])
    header=None;header_cells=[];found=[]
    for row_index,cells in enumerate(rows):
        cells.sort(key=lambda x:x[1][0]);raw=' | '.join(t for t,_ in cells)
        if sum(bool(re.fullmatch(r'(?:Min|Typ|Max|Minimum|Typical|Maximum|Unit|Units|Rating|Ratings|Feature|Description)\.?',t.strip(),re.I)) for t,_ in cells)>=2:
            header=raw;header_cells=cells.copy();header_context='\n'.join(' | '.join(t for t,_ in rr) for rr in rows[max(0,row_index-3):row_index+1]);continue
        if header is None or len(cells)<2 or len(raw)>2000:continue
        label=cells[0][0]
        if re.match(r'^\d',label):continue
        if not TOPIC.search(raw) and not re.fullmatch(r'(?:V|I|f|T)[A-Za-z0-9_ ]{1,15}',label):continue
        if not any(re.match(r'^[≤≥<>±+−–-]?\s*\d',t) for t,_ in cells[1:]):continue
        if EXCLUDE.search(raw):continue
        box=[min(b[0] for _,b in cells),min(b[1] for _,b in cells),max(b[2] for _,b in cells),max(b[3] for _,b in cells)]
        found.append({'label':label[:250],'value_text':raw,'unit_text':None,'min_text':None,'typ_text':None,'max_text':None,'conditions_text':None,'applicability_text':None,'kind':'table_row','review_status':'pending','source':{'page':page_no,'bbox':box,'snippet':raw,'context':('Header context: '+header_context+'\nNearby rows: '+'\n'.join(' | '.join(t for t,_ in rr) for rr in rows[max(0,row_index-1):row_index+3]))[:3000],'table_headers':[{'text':t,'bbox':b} for t,b in header_cells],'table_cells':[{'text':t,'bbox':b} for t,b in cells]}})
    return found


def extract_pdf(path, original_filename=None):
    import pymupdf
    specs=[]; skipped=[]; text_pages=0; seen=set(); total_chars=0
    with pymupdf.open(path) as doc:
        if doc.needs_pass: raise APIError('Password-protected PDF; provide an unlocked copy')
        if len(doc)>2500: raise APIError('PDF exceeds 2500-page processing budget')
        identity_text='\n'.join(doc[i].get_text() for i in range(min(3,len(doc))))
        manufacturer=next((name for token,name in MFR if token in identity_text.lower()),'Unverified manufacturer')
        candidates=list(dict.fromkeys(m.group(0) for m in MODEL.finditer(identity_text)))
        # This is a document-level draft, not an assertion of a single orderable part.
        model=candidates[0] if candidates else Path(original_filename or path).stem[:100]
        for pi,page in enumerate(doc):
            lines=page_lines(page)
            chars=sum(len(s) for s,_ in lines); total_chars+=chars
            if total_chars>20000000: raise APIError('PDF exceeds text processing budget')
            if chars<40: skipped.append(pi+1);continue
            text_pages+=1
            if any(re.fullmatch(r'(?:table of )?contents|list of (?:tables|figures)',t.strip(),re.I) for t,_ in lines[:12]) or sum('....' in t for t,_ in lines)>=5:continue
            specs.extend(table_excerpts(lines,pi+1))
            # Feature prose: preserve continuation lines until the next bullet/paragraph boundary.
            for j,(line,box) in enumerate(lines):
                if not TOPIC.search(line) and not PACKAGE.search(line):continue
                if EXCLUDE.search(line) or len(line)>450:continue
                chosen=[(line,box)]
                for nxt,nb in lines[j+1:j+3]:
                    if nb[1]<chosen[-1][1][1] or nb[1]-chosen[-1][1][3]>12 or abs(nb[0]-box[0])>45:break
                    if re.match(r'^[•●▪]',nxt):break
                    if TOPIC.search(nxt) and VALUE.search(nxt):break
                    if VALUE.search('\n'.join(x[0] for x in chosen)):break
                    chosen.append((nxt,nb))
                raw='\n'.join(x[0] for x in chosen)
                if not VALUE.search(raw) and not PACKAGE.search(raw):continue
                if not re.search(r'\d',raw):continue
                # Do not accept lone graph labels / generic axis units.
                if len(raw)<12 or len(re.findall(r'[A-Za-z]{3,}',raw))<2:continue
                key=(pi+1,raw)
                if key in seen:continue
                seen.add(key)
                bbox=[min(b[0] for _,b in chosen),min(b[1] for _,b in chosen),max(b[2] for _,b in chosen),max(b[3] for _,b in chosen)]
                specs.append({'label':line[:250],'value_text':raw,'unit_text':None,'min_text':None,'typ_text':None,'max_text':None,'conditions_text':None,'applicability_text':None,'kind':'verbatim_excerpt','review_status':'pending','source':{'page':pi+1,'bbox':bbox,'snippet':raw,'context':'\n'.join(s for s,_ in lines[max(0,j-2):j+4])[:3000]}})
        page_count=len(doc)
    # Drop exact duplicate evidence only; preserve different pages, units and conditions.
    unique={}
    for spec in specs:unique.setdefault((spec['source']['page'],spec['value_text']),spec)
    specs=list(unique.values())
    if not specs:raise APIError('No evidence-backed specification excerpts found; OCR or manual review required')
    if len(specs)>5000:raise APIError('More than 5000 specification excerpts; split document into sections')
    return {'model':model,'manufacturer':manufacturer,'category':None,'parameters':[], 'specifications':specs,'document_identity':{'kind':'document_family','model_candidates':candidates[:100],'verified':False},'coverage':{'total_pages':page_count,'text_pages_scanned':text_pages,'pages_without_usable_text':skipped,'all_pages_scanned':True},'warnings':['Verbatim candidates require review; no scalar values or variant assignments inferred.','Identity is a document/family draft; confirm manufacturer and applicable part numbers before publication.']}


def normalize_specifications(records):
    if not isinstance(records,list) or len(records)>5000:raise APIError('specifications must be a list of at most 5000 records')
    out=[]
    for r in records:
        if not isinstance(r,dict):raise APIError('Invalid specification')
        clean={}
        for key,limit in [('label',250),('value_text',4000),('unit_text',100),('min_text',500),('typ_text',500),('max_text',500),('conditions_text',2000),('applicability_text',1000)]:
            value=r.get(key)
            if value is not None and (not isinstance(value,str) or len(value)>limit):raise APIError('Invalid specification '+key)
            clean[key]=value
        if not clean['label'] or not clean['value_text']:raise APIError('Specification needs label and verbatim value_text')
        source=r.get('source',{})
        if not isinstance(source,dict):raise APIError('Invalid specification source')
        page=source.get('page')
        if isinstance(page,bool) or not isinstance(page,int) or page<1:raise APIError('Specification source needs a positive page')
        snippet=source.get('snippet')
        if not isinstance(snippet,str) or not snippet or len(snippet)>4000:raise APIError('Specification needs source evidence')
        box=source.get('bbox')
        if box is not None:
            import math
            if not isinstance(box,list) or len(box)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in box):raise APIError('Invalid evidence bbox')
        context=source.get('context','')
        if not isinstance(context,str) or len(context)>3000:raise APIError('Invalid evidence context')
        clean.update(kind='table_row' if r.get('kind')=='table_row' else 'verbatim_excerpt',review_status='pending',source={'page':page,'snippet':snippet,'bbox':box,'context':context})
        origin=source.get('task_id')
        if origin is not None:
            if isinstance(origin,bool) or not isinstance(origin,int) or origin<1:raise APIError('Invalid source task_id')
            clean['source']['task_id']=origin
        for key in ('table_headers','table_cells'):
            cells=source.get(key,[])
            if not isinstance(cells,list) or len(cells)>100:raise APIError('Invalid table evidence')
            for cell in cells:
                if not isinstance(cell,dict) or not isinstance(cell.get('text'),str) or len(cell['text'])>2000:raise APIError('Invalid table cell')
                b=cell.get('bbox')
                import math
                if not isinstance(b,list) or len(b)!=4 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in b):raise APIError('Invalid cell coordinates')
            clean['source'][key]=cells
        out.append(clean)
    return out
