"""Create local demo users and sample documents; never reset existing passwords."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import json,secrets
from contextlib import closing
from werkzeug.security import generate_password_hash
from backend import create_app
from backend.db import connect,log

def sample_pdf(path):
    lines=['Model: DEMO-LDO33','Manufacturer: Demo Electronics','Category: ic','Voltage: 3.3V','Current: 500mA','Package: SOT-23']
    commands='BT /F1 14 Tf 50 760 Td '+ ' 0 -24 Td '.join('('+line+') Tj' for line in lines)+' ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',f'<< /Length {len(commands)} >>\nstream\n{commands}\nendstream'.encode()]
    out=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(out));out.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(out);out.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for off in offsets[1:]:out.extend(f'{off:010d} 00000 n \n'.encode())
    out.extend(f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode());path.write_bytes(out)

def main():
    app=create_app();root=Path(app.instance_path);credentials=root/'demo-credentials.json'
    accounts=json.loads(credentials.read_text()) if credentials.exists() else {}
    with closing(connect(app.config['DATABASE'])) as db, db:
        for name,role in [('admin','admin'),('auditor','auditor'),('demo','user')]:
            if db.execute('SELECT 1 FROM users WHERE username=?',(name,)).fetchone():continue
            password=secrets.token_urlsafe(15)
            uid=db.execute('INSERT INTO users(username,password_hash,role) VALUES(?,?,?)',(name,generate_password_hash(password),role)).lastrowid
            log(db,uid,'seed_demo','user',uid);accounts[name]={'role':role,'password':password}
    credentials.write_text(json.dumps(accounts,indent=2),encoding='utf-8')
    sample_pdf(Path(__file__).resolve().parents[1]/'examples'/'demo_datasheet.pdf')
    from openpyxl import Workbook
    book=Workbook();sheet=book.active
    sheet.append(['model','manufacturer','category','voltage','current','package'])
    sheet.append(['DEMO-OPAMP','Demo Electronics','ic','5V','2mA','SOIC-8'])
    book.save(Path(__file__).resolve().parents[1]/'examples'/'components.xlsx')
    print('Demo users ready. Local credentials file: instance/demo-credentials.json (not committed or included in release ZIP).')
    print('Generated examples/demo_datasheet.pdf and examples/components.xlsx; sample values are fictional.')

if __name__=='__main__':main()
