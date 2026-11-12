"""Package tracked deliverables only; exclude instance secrets and environments."""
import hashlib,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
names=[n for n in names if n]
if not names:raise SystemExit('Stage reviewed deliverables in git before packaging')
for name in names:
    parts=Path(name).parts
    if any(x in parts for x in ('instance','.venv','.git','__pycache__','.pytest_cache','dist')) or name=='.env' or 'credentials' in Path(name).name:
        raise SystemExit(f'Refusing to package private/runtime path: {name}')
out=root/'dist';out.mkdir(exist_ok=True)
target=out/'component-extractor-backend-v1.0.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for name in sorted(names):archive.write(root/name,'component-extractor-backend/'+name)
digest=hashlib.sha256(target.read_bytes()).hexdigest()
(out/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
print(f'Release: {len(names)} files, {target.stat().st_size} bytes; secrets/runtime excluded')
