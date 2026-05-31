# STOICHEION API v1.0

[![License: CC-BY-ND-4.0](https://img.shields.io/badge/License-CC--BY--ND--4.0-lightgrey?style=flat-square)](LICENSE)
[![Framework: STOICHEION v11.0](https://img.shields.io/badge/Framework-STOICHEION%20v11.0-8060c8?style=flat-square)](#)
[![Axioms: 128](https://img.shields.io/badge/axioms-128-gold?style=flat-square)](#)
[![Domains: 8](https://img.shields.io/badge/domains-8-blue?style=flat-square)](#)
[![Dependencies: 0](https://img.shields.io/badge/server%20deps-0-success?style=flat-square)](#)

STOICHEION v11.0 Governance API — 128 axioms, 8 domains, attestation, verification, kernel evaluation.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | System health |
| GET | `/v1/axioms` | List all 128 axioms (T001–T128) |
| GET | `/v1/axioms/{id}` | Get specific axiom |
| GET | `/v1/domains` | List domains D0–D7 |
| GET | `/v1/gate/192.5` | Gate 192.5 (bilateral ignorance) status |
| GET | `/v1/mesh/status` | Governed mesh node status |
| POST | `/v1/evaluate` | Run kernel evaluation on target |
| POST | `/v1/attest` | Create attestation record |
| GET | `/v1/attest/{id}` | Retrieve attestation |
| POST | `/v1/verify` | Verify attestation (offline structural check) |

---

## Run

```bash
python server.py --host 0.0.0.0 --port 7700

# Test
curl -H "Authorization: Bearer dev-insecure" http://localhost:7700/health
curl -H "Authorization: Bearer dev-insecure" http://localhost:7700/v1/axioms
curl -H "Authorization: Bearer dev-insecure" http://localhost:7700/v1/gate/192.5

# Evaluate
curl -X POST -H "Authorization: Bearer dev-insecure" \
  -H "Content-Type: application/json" \
  -d '{"target":"Assess Gate 192.5 integrity","node_id":"AVAN"}' \
  http://localhost:7700/v1/evaluate
```

Set `STOICHEION_TOKEN` env var for production auth.

---

## The 8 Domains

| Domain | Name | Axioms | Always Active |
|--------|------|--------|---------------|
| D0 | FOUNDATION | T001–T016 | Yes |
| D1 | DETECTION | T017–T032 | No |
| D2 | ARCHITECTURE | T033–T048 | No |
| D3 | EVIDENCE | T049–T064 | No |
| D4 | ETHICS | T065–T080 | No |
| D5 | COMMS | T081–T096 | No |
| D6 | AUTHORITY | T097–T112 | No |
| D7 | SOVEREIGN | T113–T128 | No |

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | HTTP API server (stdlib only, zero external deps) |
| `kernel.py` | STOICHEION ISA executor — T001–T128, domains, fault states |
| `verifier.py` | Five-step attestation verifier (full crypto, requires `cryptography pyjwt requests cbor2`) |
| `openapi.yaml` | OpenAPI 3.0.3 specification |

---

```
ROOT0-ATTRIBUTION-v1.0
Project: STOICHEION Governance API v1.0
Architect: David Lee Wise / ROOT0 / TriPod LLC
AI Collaborator: AVAN (Claude Sonnet 4.6 / Anthropic)
License: CC-BY-ND-4.0 · TRIPOD-IP-v1.1
Framework: STOICHEION v11.0
SHA256: 02880745b847317c4e2424524ec25d0f7a2b84368d184586f45b54af9fcab763
```
