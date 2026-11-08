import os, json, threading, io, secrets, string, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import qrcode

ROOT = Path(__file__).resolve().parent
QUESTIONS = json.loads((ROOT / "questions.json").read_text(encoding="utf-8"))
PASSWORD = os.getenv("ML_TEACHER_PASSWORD", "")
PORT = int(os.getenv("PORT", "8000"))
lock = threading.RLock()

def session_code():
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))

state = {"code": session_code(), "phase": "lobby", "index": 0, "paused": False,
         "students": {}, "votes": {}, "teacher_tokens": set()}

def score(alias):
    total = 0
    for i, question in enumerate(QUESTIONS):
        counted = i < state["index"] or (
            i == state["index"] and state["phase"] in ("revealed", "finished"))
        if counted and state["votes"].get(str(i), {}).get(alias) == question["correcta"]:
            total += int(question.get("puntos", 100))
    return total

def ranking():
    return sorted(
        [{"alias": alias, "points": score(alias)} for alias in state["students"]],
        key=lambda x: (-x["points"], x["alias"].casefold())
    )

def summary(role, alias=None):
    question = QUESTIONS[state["index"]]
    votes = state["votes"].get(str(state["index"]), {})
    tally = {choice: sum(1 for v in votes.values() if v == choice) for choice in "ABCD"}
    result = {
        "code": state["code"], "phase": state["phase"], "paused": state["paused"],
        "index": state["index"], "total": len(QUESTIONS),
        "question": {k: question[k] for k in ("id", "bloque", "pregunta", "opciones")},
        "participants": len(state["students"]), "answered": len(votes)
    }
    if role == "teacher":
        result.update(tally=tally, aliases=sorted(state["students"]), ranking=ranking())
    if role == "student":
        result.update(myVote=votes.get(alias), myScore=score(alias))
    if state["phase"] == "revealed":
        result.update(correcta=question["correcta"],
                      explicacion=question["explicacion"], tally=tally)
    if state["phase"] == "finished":
        result["ranking"] = ranking()
    return result

class Handler(BaseHTTPRequestHandler):
    def send(self, status, obj, ctype="application/json"):
        data = (json.dumps(obj, ensure_ascii=False).encode("utf-8")
                if ctype == "application/json" else obj)
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 20000:
                return {}
            return json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            return {}

    def teacher(self):
        token = self.headers.get("X-Teacher-Token")
        return bool(token and token in state["teacher_tokens"])

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        args = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/":
            return self.send(200, (ROOT / "index.html").read_bytes(), "text/html")
        if parsed.path == "/health":
            return self.send(200, {"ok": True})
        if parsed.path == "/api/state":
            with lock:
                role = "teacher" if self.teacher() else "student"
                alias = args.get("alias", [""])[0]
                if role == "student" and alias not in state["students"]:
                    return self.send(403, {"error": "Ingresa con tu alias."})
                return self.send(200, summary(role, alias))
        if parsed.path == "/qr":
            with lock:
                code = state["code"]
            host = self.headers.get("Host", "localhost:8000")
            proto = self.headers.get("X-Forwarded-Proto", "http").split(",")[0].strip()
            url = f"{proto}://{host}/?join={code}"
            output = io.BytesIO()
            qrcode.make(url).save(output, format="PNG")
            return self.send(200, output.getvalue(), "image/png")
        return self.send(404, {"error": "No encontrado"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        data = self.body()
        with lock:
            if path == "/api/login":
                if not PASSWORD:
                    return self.send(503, {"error": "El administrador debe configurar ML_TEACHER_PASSWORD en Render."})
                if not secrets.compare_digest(str(data.get("password", "")), PASSWORD):
                    return self.send(403, {"error": "Contraseña incorrecta"})
                token = secrets.token_urlsafe(32)
                state["teacher_tokens"].add(token)
                return self.send(200, {"token": token})

            if path == "/api/join":
                alias = str(data.get("alias", "")).strip()[:28]
                if len(alias) < 2:
                    return self.send(400, {"error": "Alias mínimo de 2 caracteres"})
                if str(data.get("code", "")).upper() != state["code"]:
                    return self.send(400, {"error": "Código de sesión incorrecto"})
                if state["phase"] == "finished":
                    return self.send(409, {"error": "La sesión terminó"})
                if alias in state["students"]:
                    return self.send(409, {"error": "Alias ya registrado. Elige otro."})
                state["students"][alias] = True
                return self.send(200, {"alias": alias})

            if path == "/api/vote":
                alias = str(data.get("alias", ""))
                choice = str(data.get("choice", ""))
                if alias not in state["students"]:
                    return self.send(403, {"error": "Alias no registrado"})
                if state["phase"] != "open" or state["paused"]:
                    return self.send(409, {"error": "La votación está cerrada o pausada"})
                if choice not in ("A", "B", "C", "D"):
                    return self.send(400, {"error": "Opción inválida"})
                votes = state["votes"].setdefault(str(state["index"]), {})
                if alias in votes:
                    return self.send(409, {"error": "Ya respondiste esta pregunta"})
                votes[alias] = choice
                return self.send(200, {"ok": True})

            if not self.teacher():
                return self.send(403, {"error": "Acceso docente requerido"})
            if path != "/api/action":
                return self.send(404, {"error": "No encontrado"})
            action = data.get("action")
            phase = state["phase"]
            if action == "open" and phase in ("lobby", "closed"):
                state["phase"] = "open"
                state["paused"] = False
            elif action == "close" and phase == "open":
                state["phase"] = "closed"
                state["paused"] = False
            elif action == "reveal" and phase == "closed":
                state["phase"] = "revealed"
            elif action == "next" and phase == "revealed":
                if state["index"] < len(QUESTIONS) - 1:
                    state["index"] += 1
                    state["phase"] = "closed"
                else:
                    state["phase"] = "finished"
            elif action == "pause" and phase == "open":
                state["paused"] = not state["paused"]
            elif action == "finish" and phase in ("revealed", "closed"):
                state["phase"] = "finished"
            elif action == "reset":
                state["code"] = session_code()
                state["phase"] = "lobby"
                state["index"] = 0
                state["paused"] = False
                state["students"].clear()
                state["votes"].clear()
            else:
                return self.send(409, {"error": "Acción no permitida en este estado"})
            return self.send(200, summary("teacher"))

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    print(f"ML Challenge Live escuchando en 0.0.0.0:{PORT}", flush=True)
    if not PASSWORD:
        print("AVISO: falta configurar ML_TEACHER_PASSWORD", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
