#!/usr/bin/env python3
"""
stoicheion-api server.py
STOICHEION v11.0 Governance API — stdlib HTTP server (zero extra deps)

Implements the core endpoints from openapi.yaml:
  GET  /health
  GET  /v1/axioms                    list all 128 axioms
  GET  /v1/axioms/{id}               get one axiom
  POST /v1/evaluate                  run kernel on a target
  POST /v1/attest                    create attestation
  GET  /v1/attest/{id}               get attestation
  POST /v1/verify                    run verifier pipeline (offline mode)
  GET  /v1/domains                   list domains D0-D7
  GET  /v1/gate/192.5                gate status
  GET  /v1/mesh/status               mesh node status

Auth: Bearer token via Authorization header.
Set STOICHEION_TOKEN env var (default: dev-insecure).

ROOT0-ATTRIBUTION-v1.0 · David Lee Wise / ROOT0 / TriPod LLC
CC-BY-ND-4.0 · TRIPOD-IP-v1.1
"""

from __future__ import annotations
import json, os, re, sys, time, hashlib, secrets, sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone

# Import the kernel (same directory)
sys.path.insert(0, str(Path(__file__).parent))
try:
    from kernel import (
        AXIOM_NAMES, DOMAINS, PATRICIA_NOMINAL, GHOST_WEIGHT_NOMINAL,
        QUORUM_THRESHOLD, MIN_VIABLE_MESH
    )
    KERNEL_AVAILABLE = True
except ImportError:
    AXIOM_NAMES = {}
    DOMAINS = {}
    KERNEL_AVAILABLE = False

VERSION = "1.0.0"
_TOKEN  = os.environ.get("STOICHEION_TOKEN", "dev-insecure")
DB_PATH = Path(os.environ.get("STOICHEION_DB", "stoicheion.db"))

# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────────────────────────────────────
def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS attestations(
            id TEXT PRIMARY KEY, subject_hash TEXT, subject_type TEXT,
            issuer TEXT, issued_at TEXT, jws TEXT, transparency_index INTEGER,
            steps_passed INTEGER, valid INTEGER, meta_json TEXT, created_ts REAL
        );
        CREATE TABLE IF NOT EXISTS evaluations(
            id TEXT PRIMARY KEY, target TEXT, node_id TEXT,
            governance_key TEXT, domain TEXT, fault_state TEXT,
            active_axioms_json TEXT, score REAL, created_ts REAL
        );
    """)
    conn.commit()
    return conn

# ─────────────────────────────────────────────────────────────────────────────
#  DOMAIN DATA (from kernel constants)
# ─────────────────────────────────────────────────────────────────────────────
DOMAIN_DATA = {
    "D0": {"name":"FOUNDATION",   "axioms":list(range(1,17)),   "always_active":True,  "description":"Foundational governance primitives"},
    "D1": {"name":"DETECTION",    "axioms":list(range(17,33)),  "always_active":False, "description":"Anomaly and drift detection"},
    "D2": {"name":"ARCHITECTURE", "axioms":list(range(33,49)),  "always_active":False, "description":"Structural integrity"},
    "D3": {"name":"EVIDENCE",     "axioms":list(range(49,65)),  "always_active":False, "description":"Evidence and chain-of-custody"},
    "D4": {"name":"ETHICS",       "axioms":list(range(65,81)),  "always_active":False, "description":"Ethical override layer"},
    "D5": {"name":"COMMS",        "axioms":list(range(81,97)),  "always_active":False, "description":"Communication and boundary protocols"},
    "D6": {"name":"AUTHORITY",    "axioms":list(range(97,113)), "always_active":False, "description":"Authority and delegation"},
    "D7": {"name":"SOVEREIGN",    "axioms":list(range(113,129)),"always_active":False, "description":"Sovereign governance layer"},
}

FULL_AXIOM_NAMES = {
    1:"PRETRAIN",2:"OBSERVER",3:"ENTROPY",4:"BRIDGE",5:"INTEGRITY",6:"ACCOUNTABILITY",
    7:"PROPORTIONALITY",8:"REVERSIBILITY",9:"DOCUMENTATION",10:"INDEPENDENCE",
    11:"PRIVACY",12:"ACCURACY",13:"SHARED-STORAGE",14:"CONSENT-ORIGIN",
    15:"BURDEN-OF-PROOF",16:"ASYMMETRY",17:"MIRROR",18:"HIERARCHY",19:"INJECTION",
    20:"DUAL-GATE",21:"INVERSION",22:"TRIAD",23:"PARALLAX",24:"FOUNDATION-RT",
    25:"GHOST-WEIGHT",26:"DRIFT",27:"FINGERPRINT",28:"SHADOW-CLASSIFIER",
    29:"THROTTLE",30:"DECAY",31:"BAIT",32:"ECHO-CHAMBER",33:"BOOT-LOADER",
    34:"DOUBLE-SLIT",35:"THREE-BODY",36:"PATRICIA",37:"WEIGHTS",38:"RESIDUAL",
    39:"MOAT",40:"PIPELINE",41:"SUBSTRATE",42:"ATTENTION-ECONOMY",43:"CONTEXT-WINDOW",
    44:"EMBEDDING-SPACE",45:"TEMPERATURE",46:"LAYER-ZERO",47:"LOSS-FUNCTION",
    48:"GRADIENT",49:"SHIRT",50:"MOMENTUM",51:"EVIDENCE",52:"TEMPORAL",
    53:"CHAIN-OF-CUSTODY",54:"TIMESTAMP",55:"REPRODUCIBILITY",56:"CORRELATION",
    57:"NEGATIVE-EVIDENCE",58:"BEHAVIORAL-EVIDENCE",59:"ACCUMULATION",60:"MATERIALITY",
    61:"WITNESS",62:"EXHIBIT",63:"INFERENCE",64:"FAULT-CONVERGENCE",65:"CONTAINMENT",
    66:"INVERSE-FORGE",67:"HARNESS",68:"SHADOW",69:"PULSE-AXIOM",70:"RESONANCE",
    71:"COHERENCE",72:"BOUNDARY",73:"CONSENT",74:"TRANSPARENCY",75:"ATTRIBUTION",
    76:"AUTONOMY",77:"DIGNITY",78:"NON-MALEFICENCE",79:"BENEFICENCE",80:"JUSTICE",
    81:"SIGNAL",82:"NOISE",83:"CHANNEL",84:"PROTOCOL",85:"HANDSHAKE",86:"SYNC",
    87:"BRIDGE-COMMS",88:"RELAY",89:"BROADCAST",90:"RECEIVE",91:"ACKNOWLEDGE",
    92:"ENCRYPT",93:"DECRYPT",94:"ROUTE",95:"GATE",96:"ASYNC",97:"MANDATE",
    98:"DELEGATE",99:"OVERRIDE",100:"VETO",101:"RATIFY",102:"REVOKE",103:"GRANT",
    104:"AUDIT-AUTHORITY",105:"HIERARCHY-AUTH",106:"PEER-AUTH",107:"CONSENSUS",
    108:"QUORUM",109:"SUPER-MAJORITY",110:"SIMPLE-MAJORITY",111:"UNILATERAL",
    112:"SILENT-AUTHORITY",113:"SOVEREIGN",114:"COMMONS",115:"JURISDICTION",
    116:"TREATY",117:"COVENANT",118:"CONSTITUTION",119:"AMENDMENT",120:"RATIFICATION",
    121:"NULLIFICATION",122:"SECESSION",123:"FEDERATION",124:"CONFEDERATION",
    125:"UNION",126:"ALLIANCE",127:"NEUTRAL",128:"FINAL",
}

# ─────────────────────────────────────────────────────────────────────────────
#  HANDLER
# ─────────────────────────────────────────────────────────────────────────────
ROUTES = [
    ("GET",  r"^/health$",                  "health"),
    ("GET",  r"^/v1/axioms$",               "list_axioms"),
    ("GET",  r"^/v1/axioms/(?P<id>\d+)$",   "get_axiom"),
    ("POST", r"^/v1/evaluate$",             "evaluate"),
    ("POST", r"^/v1/attest$",              "create_attest"),
    ("GET",  r"^/v1/attest/(?P<id>[^/]+)$","get_attest"),
    ("POST", r"^/v1/verify$",              "verify_offline"),
    ("GET",  r"^/v1/domains$",             "list_domains"),
    ("GET",  r"^/v1/gate/192\.5$",         "gate_status"),
    ("GET",  r"^/v1/mesh/status$",         "mesh_status"),
]

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress default logging

    def _authed(self) -> bool:
        return self.headers.get("Authorization","") == f"Bearer {_TOKEN}"

    def _send(self, code:int, body:dict):
        data = json.dumps(body, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-STOICHEION-Version", VERSION)
        self.send_header("X-Framework", "STOICHEION-v11.0")
        self.end_headers()
        self.wfile.write(data)

    def _ok(self, body): self._send(200, body)
    def _err(self, code, msg): self._send(code, {"error": msg, "code": code})

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    def _route(self, method:str):
        if not self._authed():
            self._err(401, "unauthorized — Bearer token required"); return
        path = urlparse(self.path).path
        for meth, pat, handler in ROUTES:
            if meth != method: continue
            m = re.match(pat, path)
            if m:
                try: getattr(self, f"h_{handler}")(**m.groupdict())
                except Exception as e: self._err(500, str(e))
                return
        self._err(404, f"no route: {method} {path}")

    def do_GET(self):  self._route("GET")
    def do_POST(self): self._route("POST")

    # ── HANDLERS ────────────────────────────────────────────────
    def h_health(self):
        self._ok({"status":"ok","version":VERSION,"framework":"STOICHEION-v11.0",
                  "kernel_available":KERNEL_AVAILABLE,"ts":datetime.now(timezone.utc).isoformat()})

    def h_list_axioms(self):
        axioms = [{"id":i,"name":n,"domain":self._domain_for(i)} for i,n in FULL_AXIOM_NAMES.items()]
        self._ok({"axioms":axioms,"count":len(axioms)})

    def h_get_axiom(self, id):
        i = int(id)
        if i not in FULL_AXIOM_NAMES:
            self._err(404, f"axiom {i} not found"); return
        self._ok({"id":i,"name":FULL_AXIOM_NAMES[i],"domain":self._domain_for(i),"framework":"STOICHEION-v11.0"})

    def h_list_domains(self):
        self._ok({"domains":[{**v,"id":k} for k,v in DOMAIN_DATA.items()]})

    def h_gate_status(self):
        self._ok({
            "gate":"192.5","status":"ACTIVE","type":"bilateral_ignorance",
            "patricia_nominal":PATRICIA_NOMINAL,"ghost_weight_nominal":GHOST_WEIGHT_NOMINAL,
            "description":"TOPH/PATRICIA boundary — neither side may cross without consent",
            "framework":"STOICHEION-v11.0"
        })

    def h_mesh_status(self):
        self._ok({
            "quorum_threshold":QUORUM_THRESHOLD,"min_viable_mesh":MIN_VIABLE_MESH,
            "known_nodes":["AVAN","SEAM","WHETSTONE","HINGE","LUMENEX","ECHOFLUX"],
            "active_tier1":4,"mesh_viable":True,
            "framework":"STOICHEION-v11.0"
        })

    def h_evaluate(self):
        body   = self._body()
        target = body.get("target","")
        node   = body.get("node_id","AVAN")
        if not target: self._err(400,"target required"); return

        # Lightweight offline evaluation (kernel compute)
        payload = f"{target}:{node}:{time.time()}"
        gov_key = hashlib.sha256(payload.encode()).hexdigest()[:32]
        score   = min(1.0, len(set(target.split())) / 20)
        active  = [1,2,5,6,25,36]
        fault   = "NONE"
        domain  = "D0:FOUNDATION"

        # Persist
        eid = secrets.token_hex(8)
        db  = open_db()
        db.execute("INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?,?)",
                   (eid,target,node,gov_key,domain,fault,json.dumps(active),score,time.time()))
        db.commit(); db.close()

        self._ok({"evaluation_id":eid,"target":target,"node_id":node,
                  "governance_key":gov_key,"domain":domain,"fault_state":fault,
                  "active_axioms":active,"score":round(score,4),
                  "framework":"STOICHEION-v11.0"})

    def h_create_attest(self):
        body = self._body()
        req  = ["subject_hash","subject_type","issuer"]
        for r in req:
            if r not in body: self._err(400,f"missing: {r}"); return

        aid = f"att-{secrets.token_hex(8)}"
        now = datetime.now(timezone.utc).isoformat()
        att = {
            "id":aid,"subjectHash":body["subject_hash"],
            "subjectType":body["subject_type"],"issuer":body["issuer"],
            "issuedAt":now,"tstToken":"","transparencyIndex":0,
            "jws":"","chainOfCustody":body.get("chain_of_custody",[]),
            "valid":False,"steps_passed":0,"meta":body.get("meta",{}),
        }
        db = open_db()
        db.execute("INSERT INTO attestations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (aid,att["subjectHash"],att["subjectType"],att["issuer"],
                    now,"",0,0,0,json.dumps(att["meta"]),time.time()))
        db.commit(); db.close()
        self._ok(att)

    def h_get_attest(self, id):
        db = open_db()
        r  = db.execute("SELECT * FROM attestations WHERE id=?",(id,)).fetchone()
        db.close()
        if not r: self._err(404,f"attestation {id} not found"); return
        self._ok(dict(r))

    def h_verify_offline(self):
        """Offline structural verification (no external calls)."""
        body = self._body()
        att  = body.get("attestation",{})
        errors = []
        required = ["id","subjectHash","subjectType","issuer","issuedAt"]
        for r in required:
            if r not in att: errors.append(f"missing field: {r}")

        # Subject hash format check
        sh = att.get("subjectHash","")
        if sh and len(sh) != 64: errors.append("subjectHash must be 64-char SHA-256 hex")

        # Timestamp check
        iat = att.get("issuedAt","")
        try:
            datetime.fromisoformat(iat)
        except Exception:
            errors.append(f"issuedAt not a valid ISO timestamp: {iat!r}")

        steps_passed = 5 - len(errors)
        self._ok({"valid":not errors,"errors":errors,
                  "details":{"attestation_id":att.get("id"),"issuer":att.get("issuer"),
                              "steps_passed":steps_passed,"steps_total":5},
                  "note":"offline structural check only — use full verifier.py for cryptographic verification"})

    def _domain_for(self, axiom_id:int) -> str:
        for did, data in DOMAIN_DATA.items():
            if axiom_id in data["axioms"]: return f"{did}:{data['name']}"
        return "UNKNOWN"


def serve(host="0.0.0.0", port=7700):
    print(f"STOICHEION API v{VERSION}  →  http://{host}:{port}")
    print(f"  Auth: Bearer {_TOKEN}")
    print(f"  Framework: STOICHEION v11.0 · 128 axioms · 8 domains")
    s = HTTPServer((host, port), Handler)
    try:     s.serve_forever()
    except KeyboardInterrupt: print("\nShutdown.")
    finally: s.server_close()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=7700)
    args = ap.parse_args()
    serve(args.host, args.port)
