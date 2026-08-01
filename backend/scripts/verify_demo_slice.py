import os, sys, json, time, subprocess, pathlib
BE="/sessions/stoic-quirky-thompson/mnt/ai automation tool/AI-RevenueOS/backend"
sys.path.insert(0, BE+"/src"); os.chdir(BE)
import pgserver, redislite, httpx
pgdir=pathlib.Path("/tmp/live-pg"); pg=pgserver.get_server(str(pgdir))   # already migrated+seeded
redis=redislite.Redis("/tmp/live-redis.rdb")
env={**os.environ,
 "DATABASE_URL":f"postgresql+asyncpg://airevenueos_app_login@/airevenueos?host={pgdir}",
 "MAINTENANCE_DATABASE_URL":f"postgresql+asyncpg://airevenueos_maintenance_login@/airevenueos?host={pgdir}",
 "REDIS_URL":f"unix://{redis.socket_file}","ENVIRONMENT":"local","LOG_JSON":"false","PYTHONPATH":BE+"/src"}
api=subprocess.Popen([sys.executable,"-m","uvicorn","main:app","--host","127.0.0.1","--port","8000","--app-dir","src"],
    cwd=BE,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
web=subprocess.Popen(["node","node_modules/next/dist/bin/next","start","-p","3000"],cwd="/tmp/webbuild",
    env={**os.environ,"API_INTERNAL_URL":"http://127.0.0.1:8000","NODE_ENV":"production"},
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def up(u,n=60):
    for _ in range(n):
        try:
            if httpx.get(u,timeout=1).status_code<500: return True
        except Exception: pass
        time.sleep(0.4)
    return False
try:
    print("API  :", up("http://127.0.0.1:8000/health/liveness"), "| WEB :", up("http://127.0.0.1:3000/login"), flush=True)
    c=httpx.Client(base_url="http://127.0.0.1:3000",follow_redirects=True,timeout=25)
    print("GET  /login           ->",c.get("/login").status_code,"| form:", "Sign in" in c.get("/login").text, flush=True)
    r=c.post("/api/auth/login",json={"email":"asha@acme.test","password":"demo-local-passphrase-2026"})
    print("POST /api/auth/login  ->",r.status_code,"| cookie:", any("airev-session" in k for k in c.cookies.keys()), flush=True)
    if r.status_code!=200: print("  body:",r.text[:200],flush=True)
    r=c.get("/leads"); print("GET  /leads           ->",r.status_code,"| seeded 'Meera':", "Meera" in r.text, flush=True)
    csrf=next((v for k,v in c.cookies.items() if "airev-csrf" in k), "")
    r=c.post("/api/leads",headers={"x-csrf-token":csrf},json={"first_name":"Browser","last_name":"Flow","email":f"bf-{int(time.time())}@example.in","source":"manual"})
    print("POST /api/leads       ->",r.status_code,flush=True)
    lid=r.json()["data"]["id"]; ver=r.json()["data"]["version"]
    print("GET  /leads (new row) :", "Browser" in c.get("/leads").text, flush=True)
    print("GET  /leads/{id}      ->",c.get(f"/leads/{lid}").status_code,"| name shown:", "Browser" in c.get(f"/leads/{lid}").text, flush=True)
    r=c.patch(f"/api/leads/{lid}",headers={"x-csrf-token":csrf,"if-match":f'W/"{ver}"'},json={"last_name":"Edited"})
    print("PATCH /api/leads/{id} ->",r.status_code,flush=True)
    print("page refresh shows edit:", "Edited" in c.get(f"/leads/{lid}").text, flush=True)
    c2=httpx.Client(base_url="http://127.0.0.1:3000",follow_redirects=True,timeout=25)
    c2.post("/api/auth/login",json={"email":"ravi@globex.test","password":"demo-local-passphrase-2026"})
    r=c2.get(f"/leads/{lid}"); print("tenant B opens A's URL ->",r.status_code,"| 'Not found':", "Not found" in r.text, flush=True)
    print("tenant B list leaks A :", "Browser" in c2.get("/leads").text, flush=True)
finally:
    for p in (api,web):
        try: p.terminate(); p.wait(timeout=6)
        except Exception: p.kill()
