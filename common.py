"""Small local HTTP server, SQLite helpers and optional compatible LLM client."""
import json, os, sqlite3, time, urllib.request, urllib.error, re, math
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect(path=None):
    path = Path(path or ROOT / 'storage' / 'app.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db:
            yield db
    finally:
        db.close()

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)

def require_text(value, field='text', limit=6000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'{field}: требуется непустой текст, максимум {limit} символов')
    return value.strip()

class SearchIndex:
    """Character 3–5 gram TF-IDF + cosine, fitted only on supplied documents."""
    @staticmethod
    def grams(text):
        text = ' ' + ' '.join(re.findall(r'[a-zа-яё0-9]+', text.lower().replace('ё','е'))) + ' '
        return Counter(text[i:i+n] for n in (3,4,5) for i in range(max(0,len(text)-n+1)))
    def __init__(self, docs):
        if not docs: raise ValueError('Пустой индекс')
        self.docs = docs
        counts = [self.grams(d['title']+' '+d.get('keywords','')+' '+d['body']) for d in docs]
        df = Counter(g for count in counts for g in count)
        self.idf = {g: math.log((1+len(docs))/(1+n))+1 for g,n in df.items()}
        self.vectors = [self.vector(c) for c in counts]
    def vector(self, counts):
        v={g:(1+math.log(n))*self.idf[g] for g,n in counts.items() if g in self.idf}
        norm=math.sqrt(sum(x*x for x in v.values())) or 1
        return {g:x/norm for g,x in v.items()}
    def search(self, query, limit=3):
        q=self.vector(self.grams(query))
        rows=[dict(d, score=round(sum(v.get(g,0)*x for g,x in q.items()),6)) for d,v in zip(self.docs,self.vectors)]
        return sorted(rows,key=lambda d:(-d['score'],d['id']))[:limit]

def llm(messages, model=None, prices=None):
    """No fallback on failure. Price inputs are user-supplied USD / million tokens."""
    key=os.environ.get('LLM_API_KEY','')
    model=model or os.environ.get('LLM_MODEL','')
    if not key or not model: raise ValueError('Задайте LLM_API_KEY и LLM_MODEL')
    base=os.environ.get('LLM_BASE_URL','https://api.openai.com/v1').rstrip('/')
    parsed=urlsplit(base)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise ValueError('LLM_BASE_URL: требуется HTTPS (HTTP только localhost)')
    payload=json.dumps({'model':model,'messages':messages,'temperature':0.2},ensure_ascii=False).encode()
    req=urllib.request.Request(base+'/chat/completions',data=payload,headers={
        'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    started=time.perf_counter()
    try:
        with urllib.request.urlopen(req,timeout=45) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('Слишком большой ответ модели')
        data=json.loads(raw)
        content=require_text(data['choices'][0]['message']['content'],'LLM content',30000)
    except urllib.error.HTTPError as exc:
        raise ValueError(f'Ошибка API, HTTP {exc.code}; проверьте ключ, модель и лимиты') from None
    except (urllib.error.URLError,TimeoutError):
        raise ValueError('API недоступно или истекло время ожидания') from None
    except (KeyError,IndexError,TypeError,json.JSONDecodeError):
        raise ValueError('API вернул неподдерживаемый формат ответа') from None
    usage=data.get('usage') or {}
    inp,out=usage.get('prompt_tokens'),usage.get('completion_tokens')
    cost=None
    ip=(prices or {}).get('input');op=(prices or {}).get('output')
    if prices is None and model==os.environ.get('LLM_MODEL'):
        ip=os.environ.get('LLM_INPUT_USD_PER_MILLION');op=os.environ.get('LLM_OUTPUT_USD_PER_MILLION')
    if ip is not None and op is not None and isinstance(inp,int) and isinstance(out,int):
        ip,op=float(ip),float(op)
        if not math.isfinite(ip+op) or min(ip,op)<0: raise ValueError('Тарифы должны быть конечными и >= 0')
        cost=(inp*ip+out*op)/1_000_000
    return {'text':content,'latency_ms':round((time.perf_counter()-started)*1000,3),
            'input_tokens':inp,'output_tokens':out,'cost_usd':cost,'model':model}

def serve(route, port, title):
    """Loopback only. One request at a time: suitable for a local portfolio tool."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def reply(self, code, data, mime='application/json; charset=utf-8'):
            raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if mime.startswith('application/json') else data
            self.send_response(code); self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store')
            self.end_headers(); self.wfile.write(raw)
        def do_GET(self): self.handle_request()
        def do_POST(self): self.handle_request()
        def handle_request(self):
            path=urlsplit(self.path).path
            if self.command=='GET' and path in ('/','/style.css','/common.js'):
                name={'/':'index.html','/style.css':'style.css','/common.js':'common.js'}[path]
                mime={'/':'text/html; charset=utf-8','/style.css':'text/css; charset=utf-8','/common.js':'text/javascript; charset=utf-8'}[path]
                return self.reply(200,(ROOT/'web'/name).read_bytes(),mime)
            if path=='/health': return self.reply(200,{'status':'ok','project':title})
            try:
                host=self.headers.get('Host','')
                if host not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'):
                    raise ValueError('Недопустимый Host')
                origin=self.headers.get('Origin')
                if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
                    raise ValueError('Недопустимый Origin')
                body={}
                if self.command=='POST':
                    if not self.headers.get('Content-Type','').startswith('application/json'): raise ValueError('Требуется application/json')
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=2_000_000: raise ValueError('Размер запроса: 1..2 000 000 байт')
                    body=json.loads(self.rfile.read(size))
                    if not isinstance(body,dict): raise ValueError('Требуется JSON object')
                result=route(self.command,path,parse_qs(urlsplit(self.path).query),body)
                self.reply(200,result)
            except LookupError: self.reply(404,{'error':'Не найдено'})
            except (ValueError,TypeError,json.JSONDecodeError) as exc: self.reply(400,{'error':str(exc)})
            except Exception:
                import traceback; traceback.print_exc()
                self.reply(500,{'error':'Внутренняя ошибка. Подробности в консоли.'})
    server=HTTPServer(('127.0.0.1',port),Handler)
    print(f'{title}: http://127.0.0.1:{server.server_port} (Ctrl+C — остановить)',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
