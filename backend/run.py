"""Single-process local deployment: Waitress HTTP server plus SQLite queue thread."""
import os
from waitress import serve
from backend import create_app
from backend.worker import start_worker

app=create_app()
if __name__=='__main__':
    stop,thread=start_worker(app)
    host=os.getenv('HOST','127.0.0.1');port=int(os.getenv('PORT','5000'))
    print(f'Component backend: http://{host}:{port}/api/health',flush=True)
    try:serve(app,host=host,port=port,threads=8)
    finally:stop.set();thread.join(timeout=5)
