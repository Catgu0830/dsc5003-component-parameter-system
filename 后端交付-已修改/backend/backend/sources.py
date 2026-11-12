"""Bounded document parsing and pinned-public-IP HTTP fetching (no proxy/DNS rebind)."""
import csv
import http.client
import io
import ipaddress
import json
import socket
import ssl
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import pdfplumber
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from .common import APIError

USER_AGENT = 'ComponentExtractor/1.0'
MAX_SOURCE_BYTES = 5 * 1024 * 1024


def validate_url(url, allowed_hosts=()):
    if not isinstance(url, str) or len(url) > 2000:
        raise APIError('Invalid URL')
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise APIError('Invalid URL')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise APIError('URL must be HTTP(S), with no credentials or fragment')
    if port not in (None, 80, 443):
        raise APIError('Only ports 80 and 443 are permitted')
    host = parsed.hostname.encode('idna').decode('ascii')
    if allowed_hosts and host not in allowed_hosts:
        raise APIError('URL host is not allowlisted')
    try:
        addresses = {a[4][0] for a in socket.getaddrinfo(host, port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)}
    except OSError:
        raise APIError('URL hostname cannot be resolved')
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise APIError('URL must resolve exclusively to public Internet addresses')
    return parsed, sorted(addresses)[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, ip, port):
        super().__init__(hostname, port, timeout=15, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def public_get(url, allowed_hosts=(), limit=MAX_SOURCE_BYTES, redirects=3):
    for hop in range(redirects+1):
        parsed, ip = validate_url(url, allowed_hosts)
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if parsed.scheme == 'https':
            conn = PinnedHTTPS(parsed.hostname, ip, port)
        else:
            conn = http.client.HTTPConnection(ip, port, timeout=15)
        try:
            path = (parsed.path or '/') + (('?' + parsed.query) if parsed.query else '')
            conn.request('GET', path, headers={'Host': parsed.netloc, 'User-Agent': USER_AGENT, 'Accept-Encoding': 'identity'})
            response = conn.getresponse()
            if response.status in (301,302,303,307,308):
                location = response.getheader('Location')
                if not location or hop == redirects:
                    raise APIError('Too many redirects or missing redirect target')
                url = urljoin(url, location)
                continue
            payload = response.read(limit+1)
            if len(payload) > limit:
                raise APIError('Remote response exceeds size limit')
            return response.status, payload, response.getheader('Content-Type',''), url
        finally:
            conn.close()
    raise APIError('Too many redirects')


def fetch_web(url, allowed_hosts=()):
    # Redirects are followed individually so every final origin has its own robots check.
    current = url
    for _ in range(4):
        parsed, _ = validate_url(current, allowed_hosts)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        code, rules, _, _ = public_get(origin+'/robots.txt', allowed_hosts, limit=512000)
        if code not in (200,404,410):
            raise APIError('robots.txt could not be checked; upload the document instead')
        if code == 200:
            robot = RobotFileParser(); robot.parse(rules.decode('utf-8',errors='replace').splitlines())
            if not robot.can_fetch(USER_AGENT, current):
                raise APIError('robots.txt disallows this URL')
        # Use zero redirects; redirect handling here ensures per-origin robots checks.
        try:
            status, raw, mime, final = public_get(current, allowed_hosts, redirects=0)
        except APIError as exc:
            if exc.message == 'Too many redirects or missing redirect target':
                # Obtain a redirect target without following it.
                current = redirect_target(current, allowed_hosts)
                continue
            raise
        if status != 200:
            raise APIError(f'Website returned HTTP {status}')
        if 'html' not in mime.lower() and not mime.lower().startswith('text/plain'):
            raise APIError('URL extraction supports HTML/text only; upload PDF files')
        soup = BeautifulSoup(raw, 'html.parser')
        for node in soup(['script','style','nav','footer','noscript']):
            node.decompose()
        return soup.get_text('\n', strip=True)[:120000], final
    raise APIError('Too many website redirects')


def redirect_target(url, allowed_hosts):
    parsed, ip = validate_url(url, allowed_hosts)
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    conn = PinnedHTTPS(parsed.hostname, ip, port) if parsed.scheme == 'https' else http.client.HTTPConnection(ip,port,timeout=15)
    try:
        conn.request('GET',(parsed.path or '/')+(('?'+parsed.query) if parsed.query else ''),headers={'Host':parsed.netloc,'User-Agent':USER_AGENT})
        response=conn.getresponse(); location=response.getheader('Location')
        if response.status not in (301,302,303,307,308) or not location:
            raise APIError('Redirect target unavailable')
        return urljoin(url,location)
    finally:
        conn.close()


def check_xlsx(path):
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members)>2000 or sum(x.file_size for x in members)>30*1024*1024:
                raise APIError('Excel archive expands beyond allowed size')
            if any('vbaproject' in x.filename.lower() for x in members):
                raise APIError('Macro-enabled workbooks are not supported')
    except zipfile.BadZipFile:
        raise APIError('Invalid XLSX file')


def table_records(path, source_type):
    if source_type == 'csv':
        with open(path,encoding='utf-8-sig',newline='') as f:
            csv.field_size_limit(100000)
            reader=csv.DictReader(f)
            if not reader.fieldnames or len(reader.fieldnames)>120 or len(set(reader.fieldnames))!=len(reader.fieldnames):
                raise APIError('CSV headers must be unique, with at most 120 columns')
            records=[]
            for row in reader:
                records.append(row)
                if len(records)>1000:
                    raise APIError('At most 1000 rows per import')
    else:
        check_xlsx(path)
        book=load_workbook(path,read_only=True,data_only=False,keep_links=False)
        try:
            sheet=book.active
            if sheet.max_row>1001 or sheet.max_column>120:
                raise APIError('Excel supports at most 1000 data rows and 120 columns; trim excess formatted rows')
            rows=sheet.iter_rows(values_only=True)
            headers=next(rows,None)
            if not headers or len(headers)>120:
                raise APIError('Missing or excessive Excel columns')
            headers=[str(h or '').strip() for h in headers]
            if len(set(headers))!=len(headers):
                raise APIError('Excel headers must be unique')
            records=[]
            for values in rows:
                if not any(v is not None for v in values):continue
                if any(isinstance(v,str) and v.startswith('=') for v in values):
                    raise APIError('Excel formulas are not accepted as parameter values')
                records.append(dict(zip(headers,values)))
                if len(records)>1000:raise APIError('At most 1000 rows per import')
        finally:book.close()
    if not records:
        raise APIError('Import file has no data rows')
    result=[]
    for row_no,row in enumerate(records,2):
        if None in row:raise APIError('CSV row contains too many columns')
        mapped={str(k).strip():v for k,v in row.items()}
        for chinese,english in [('型号','model'),('厂商','manufacturer'),('类别','category')]:
            if chinese in mapped:mapped[english]=mapped.pop(chinese)
        params=[]
        for key,value in mapped.items():
            if key in ('model','manufacturer','category','component_id') or key.endswith('_unit') or value is None or value=='':continue
            if key=='parameters':
                try:params.extend(json.loads(value))
                except (ValueError,TypeError):raise APIError(f'Row {row_no}: invalid parameters JSON')
            else:
                params.append({'name':key,'value':value,'unit':mapped.get(key+'_unit') or None,'confidence':1.0,'source':{'row':row_no,'snippet':f'{key}: {value}'}})
        result.append({**{k:mapped.get(k) for k in ('model','manufacturer','category')},'parameters':params})
    return result


def pdf_text(path):
    if Path(path).read_bytes()[:5] != b'%PDF-':
        raise APIError('Invalid PDF signature')
    pages=[]
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages)>100:
            raise APIError('PDF exceeds 100-page limit; split it before uploading')
        for i,page in enumerate(pdf.pages,1):
            content=page.extract_text() or ''
            pages.append(f'[PAGE {i}]\n{content}')
            if sum(map(len,pages))>120000:
                raise APIError('PDF text exceeds 120000 characters; split the document')
    content='\n'.join(pages)
    if len(''.join(content.split()))<40:
        raise APIError('No usable PDF text; scanned PDFs need OCR or manual entry')
    return content
