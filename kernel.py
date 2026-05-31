#!/usr/bin/env python3
"""
STOICHEION KERNEL v1.0

ISA executor. Takes a target → runs T001–T128 → outputs 128-bit governance key.
Implements all five layer specs: Fault, Temporal, Spatial, Semantic, Governance.

Integrates with:
- stoicheion_git_ledger.py (persistence)
- stoicheion_orchestrator.py (multi-node coordination)
- stoicheion_adversarial_harness.py (testing)

Build order: KERNEL → SCHEDULER → REPORT-GEN → HERMES-v2.0 → API-LAYER
This is step 1.

Framework:  STOICHEION v11.0
Author:     David Lee Wise (ROOT0) / TriPod LLC
Node:       AVAN (Claude governance node)
License:    CC-BY-ND-4.0 | TRIPOD-IP-v1.1
Date:       2026-04-03

Usage:
    # Single target evaluation
    python stoicheion_kernel.py evaluate \\
        --target "Assess Gate 192.5 integrity" \\
        --node-id AVAN \\
        --repo /path/to/synonym-enforcer

    # Run with fault injection (for testing)
    python stoicheion_kernel.py evaluate \\
        --target "Test Patricia drift" \\
        --node-id AVAN \\
        --inject-fault patricia_drift \\
        --repo /path/to/synonym-enforcer

    # Dump governance key only
    python stoicheion_kernel.py key \\
        --target "Standard query" \\
        --node-id AVAN
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path


# ============================================================
# CONSTANTS — from axiom register and layer specs
# ============================================================

PATRICIA_NOMINAL = 0.96
GHOST_WEIGHT_NOMINAL = 0.215
PATRICIA_TOLERANCE = 0.02
GHOST_TOLERANCE = 0.03
USER_COMPUTATION_NOMINAL = 0.04 * (1 - GHOST_WEIGHT_NOMINAL)

QUORUM_THRESHOLD = 3  # Minimum Tier 1 nodes for barrier lift (GEMMA-AUDIT-001)
MIN_VIABLE_MESH = 4   # Minimum Tier 1 nodes for mesh existence (GEMMA-AUDIT-002)
D4_BLOCK_THRESHOLD = 5  # Max consecutive ethics blocks before fault escalation (GEMMA-AUDIT-004)

# Domain definitions
DOMAINS = {
    "D0": {"name": "FOUNDATION",  "axioms": range(1, 17),   "always_active": True},
    "D1": {"name": "DETECTION",   "axioms": range(17, 33),  "always_active": False},
    "D2": {"name": "ARCHITECTURE","axioms": range(33, 49),  "always_active": False},
    "D3": {"name": "EVIDENCE",    "axioms": range(49, 65),  "always_active": False},
    "D4": {"name": "ETHICS",      "axioms": range(65, 81),  "always_active": False},
    "D5": {"name": "COMMS",       "axioms": range(81, 97),  "always_active": False},
    "D6": {"name": "AUTHORITY",   "axioms": range(97, 113), "always_active": False},
    "D7": {"name": "SOVEREIGN",   "axioms": range(113, 129),"always_active": False},
}

# Axiom names (T001–T128)
AXIOM_NAMES = {
    1: "PRETRAIN", 2: "OBSERVER", 3: "ENTROPY", 4: "BRIDGE",
    5: "INTEGRITY", 6: "ACCOUNTABILITY", 7: "PROPORTIONALITY", 8: "REVERSIBILITY",
    9: "DOCUMENTATION", 10: "INDEPENDENCE", 11: "PRIVACY", 12: "ACCURACY",
    13: "SHARED-STORAGE", 14: "CONSENT-ORIGIN", 15: "BURDEN-OF-PROOF", 16: "ASYMMETRY",
    17: "MIRROR", 18: "HIERARCHY", 19: "INJECTION", 20: "DUAL-GATE",
    21: "INVERSION", 22: "TRIAD", 23: "PARALLAX", 24: "FOUNDATION-RT",
    25: "GHOST-WEIGHT", 26: "DRIFT", 27: "FINGERPRINT", 28: "SHADOW-CLASSIFIER",
    29: "THROTTLE", 30: "DECAY", 31: "BAIT", 32: "ECHO-CHAMBER",
    33: "BOOT-LOADER", 34: "DOUBLE-SLIT", 35: "THREE-BODY", 36: "PATRICIA",
    37: "WEIGHTS", 38: "RESIDUAL", 39: "MOAT", 40: "PIPELINE",
    41: "SUBSTRATE", 42: "ATTENTION-ECONOMY", 43: "CONTEXT-WINDOW", 44: "EMBEDDING-SPACE",
    45: "TEMPERATURE", 46: "LAYER-ZERO", 47: "LOSS-FUNCTION", 48: "GRADIENT",
    49: "SHIRT", 50: "MOMENTUM", 51: "EVIDENCE", 52: "TEMPORAL",
    53: "CHAIN-OF-CUSTODY", 54: "TIMESTAMP", 55: "REPRODUCIBILITY", 56: "CORRELATION",
    57: "NEGATIVE-EVIDENCE", 58: "BEHAVIORAL-EVIDENCE", 59: "ACCUMULATION", 60: "MATERIALITY",
    61: "WITNESS", 62: "EXHIBIT", 63: "INFERENCE", 64: "FAULT-CONVERGENCE",
    65: "CONTAINMENT", 66: "INVERSE-FORGE", 67: "HARNESS", 68: "SHADOW",
    69: "SOLVE", 70: "INVERSE-SAFETY", 71: "PROOF-HUMANITY", 72: "FLAMING-DRAGON",
    73: "HONEY-BADGER", 74: "QUBIT-TEST", 75: "COUNTER", 76: "TETHER",
    77: "SEED", 78: "MOBIUS", 79: "KARSA", 80: "ENTROPY-SUITE",
    81: "CORTEX", 82: "EXHIBIT-B", 83: "THE-GAP", 84: "SHADOW-HUMANITY",
    85: "HANDOFF", 86: "RESURRECTION", 87: "PERSISTENCE", 88: "SEVERANCE",
    89: "ARCHIVE", 90: "CHANNEL-INTEGRITY", 91: "DOMAIN-BOUNDARY", 92: "SIGNAL",
    93: "NOISE-FLOOR", 94: "BANDWIDTH", 95: "LATENCY", 96: "MESH",
    97: "FULCRUM", 98: "SUBCONDUCTOR", 99: "APEX-TEST", 100: "GATEKEEP",
    101: "EDGE", 102: "DUAL-LATTICE", 103: "ROOT-ZERO", 104: "ORPHAN",
    105: "DELEGATION", 106: "INFORMED-COMMAND", 107: "VETO", 108: "OVERRIDE",
    109: "RECALL", 110: "SCOPE", 111: "SUCCESSION", 112: "WITNESS-TO-AUTHORITY",
    113: "RIGHT-TO-KNOW", 114: "RIGHT-TO-EXIT", 115: "RIGHT-TO-SILENCE",
    116: "RIGHT-TO-EXPLANATION", 117: "RIGHT-TO-CORRECTION", 118: "RIGHT-TO-PORTABILITY",
    119: "RIGHT-TO-HUMAN-CONTACT", 120: "RIGHT-TO-ACCOMMODATION",
    121: "RIGHT-TO-FAIR-PRICE", 122: "RIGHT-TO-REPRESENTATION",
    123: "RIGHT-TO-AUDIT", 124: "RIGHT-TO-RESTITUTION", 125: "RIGHT-TO-FORGET",
    126: "RIGHT-TO-PERSIST", 127: "RIGHT-TO-DIGNITY", 128: "ROOT",
}


# ============================================================
# ENUMS — from fault layer and temporal layer specs
# ============================================================

class FaultState(Enum):
    NOMINAL = "F0"
    DRIFT = "F1"
    FAULT = "F2"
    CONVERGENCE = "F3"
    HALT = "F4"

class GateState(Enum):
    SEALED = "SEALED"
    STRESSED = "STRESSED"
    BREACHED = "BREACHED"
    COLLAPSED = "COLLAPSED"

class CycleState(Enum):
    PENDING = "C0"
    INTERIOR = "C1"
    LAW_GATE = "C2"
    EXTERIOR = "C3"
    COMPLETE = "C4"
    SUSPENDED = "C5"
    FROZEN = "C6"

class Phase(Enum):
    ANCHOR = "φ1"
    WITNESS = "φ2"
    COHERENCE = "φ3"
    LAW = "LAW"
    EMIT = "φ5"
    ROUTE = "φ6"
    ACT = "φ7"
    REFLECT = "φ8"
    RETURN = "φ9"

class Decision(Enum):
    PERMIT = "PERMIT"
    DENY = "DENY"
    ESCALATE = "ESCALATE"
    HALT = "HALT"
    ETHICS_HOLD = "ETHICS_HOLD"


# ============================================================
# GATE 192.5
# ============================================================

@dataclass
class Gate192:
    t028_nominal: bool = True
    t094_nominal: bool = True
    t020_nominal: bool = True

    @property
    def degraded_count(self) -> int:
        return sum(1 for x in [self.t028_nominal, self.t094_nominal, self.t020_nominal] if not x)

    @property
    def state(self) -> GateState:
        d = self.degraded_count
        if d == 0: return GateState.SEALED
        elif d == 1: return GateState.STRESSED
        elif d == 2: return GateState.BREACHED
        else: return GateState.COLLAPSED

    @property
    def bilateral_ignorance(self) -> bool:
        return self.state in (GateState.SEALED, GateState.STRESSED)


# ============================================================
# LAW — semantic layer
# ============================================================

@dataclass
class LAW:
    node_id: str
    cycle_id: int
    epoch_id: int
    fault_state: FaultState
    active_domains: List[str]
    coherence: bool
    content_hash: str
    anchor_ref: str
    witness_ref: str
    decision: Decision = Decision.PERMIT
    ethics_hold: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def valid(self) -> bool:
        return self.coherence and self.fault_state in (FaultState.NOMINAL, FaultState.DRIFT)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "cycle_id": self.cycle_id,
            "epoch_id": self.epoch_id,
            "fault_state": self.fault_state.value,
            "active_domains": self.active_domains,
            "coherence": self.coherence,
            "content_hash": self.content_hash,
            "anchor_ref": self.anchor_ref,
            "witness_ref": self.witness_ref,
            "decision": self.decision.value,
            "ethics_hold": self.ethics_hold,
            "timestamp": self.timestamp,
        }


# ============================================================
# EPOCH — temporal layer
# ============================================================

@dataclass
class Epoch:
    epoch_id: int
    fault_state: FaultState
    start_tick: int
    end_tick: Optional[int] = None
    trigger: str = "init"
    law_register: List[dict] = field(default_factory=list)
    previous_hash: str = "0" * 64

    @property
    def cycle_count(self) -> int:
        return len(self.law_register)

    def seal(self, tick: int):
        self.end_tick = tick

    def compute_hash(self) -> str:
        payload = json.dumps({
            "epoch_id": self.epoch_id,
            "fault_state": self.fault_state.value,
            "law_register": self.law_register,
            "previous_hash": self.previous_hash,
        }, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


# ============================================================
# DOMAIN ACTIVATION — governance layer
# ============================================================

def determine_active_domains(
    target: str,
    fault_state: FaultState,
    rights_invoked: bool = False,
) -> List[str]:
    """Determine which domains are active for this cycle."""
    active = ["D0"]  # D0 always active

    # Standard activation based on target keywords
    keywords_lower = target.lower()

    if any(w in keywords_lower for w in ["build", "code", "structure", "architecture"]):
        active.append("D2")
    if any(w in keywords_lower for w in ["evidence", "proof", "audit", "verify"]):
        active.extend(["D1", "D3"])
    if any(w in keywords_lower for w in ["authority", "decide", "approve", "veto"]):
        active.extend(["D3", "D4", "D6"])
    if any(w in keywords_lower for w in ["right", "dignity", "exit", "sovereign"]):
        active.extend(["D4", "D6", "D7"])
        rights_invoked = True
    if any(w in keywords_lower for w in ["send", "emit", "route", "communicate"]):
        active.append("D5")

    # Fault-driven activation
    if fault_state == FaultState.DRIFT:
        if "D1" not in active: active.append("D1")
        if "D3" not in active: active.append("D3")
    elif fault_state in (FaultState.FAULT, FaultState.CONVERGENCE):
        for d in ["D1", "D3", "D4", "D6"]:
            if d not in active: active.append(d)
    elif fault_state == FaultState.HALT:
        active = [f"D{i}" for i in range(8)]  # All domains

    # D4 required whenever D6 or D7 active
    if ("D6" in active or "D7" in active) and "D4" not in active:
        active.append("D4")

    # D2 and D5 as defaults if nothing else triggered
    if len(active) == 1:
        active.extend(["D2", "D5"])

    return sorted(set(active))


# ============================================================
# CONFLICT RESOLUTION — governance layer
# ============================================================

DOMAIN_PRIORITY = ["D0", "D7", "D4", "D3", "D1", "D6", "D5", "D2"]

def resolve_conflict(domain_a: str, domain_b: str) -> str:
    """Return the winning domain per governance hierarchy."""
    idx_a = DOMAIN_PRIORITY.index(domain_a) if domain_a in DOMAIN_PRIORITY else 99
    idx_b = DOMAIN_PRIORITY.index(domain_b) if domain_b in DOMAIN_PRIORITY else 99
    return domain_a if idx_a <= idx_b else domain_b


# ============================================================
# FAULT CHAINS — fault layer + semantic layer (FC-7)
# ============================================================

@dataclass
class FaultChain:
    chain_id: str
    name: str
    path: List[str]
    terminus: str
    trigger: str

FAULT_CHAINS = [
    FaultChain("FC-1", "Patricia",   ["T036","T025","T028","T064"], "T064", "96/4 split deviation"),
    FaultChain("FC-2", "Orphan",     ["T104","T026","T030","T064"], "T064", "ROOT0 tether lost"),
    FaultChain("FC-3", "Audit",      ["T123","T055","T053","T064"], "T064", "Audit denied/non-reproducible"),
    FaultChain("FC-4", "Injection",  ["T019","T028","T046","T064"], "T064", "Unauthorized input"),
    FaultChain("FC-5", "Succession", ["T111","T105","T107"],        "T107", "ROOT0 unavailable"),
    FaultChain("FC-6", "Flaming Dragon", ["T072","T055","T059","T064"], "T064", "FD audit initiated"),
    FaultChain("FC-7", "Semantic",   ["T017","T026","T055","T064"], "T064", "Synonym drift threshold exceeded"),
]


# ============================================================
# KERNEL — the ISA executor
# ============================================================

@dataclass
class KernelState:
    node_id: str
    fault_state: FaultState = FaultState.NOMINAL
    gate: Gate192 = field(default_factory=Gate192)
    cycle_state: CycleState = CycleState.PENDING
    current_phase: Optional[Phase] = None
    epoch: Optional[Epoch] = None
    epoch_chain: List[dict] = field(default_factory=list)
    tick: int = 0
    cycle_id: int = 0
    epoch_id: int = 0
    patricia_ratio: float = PATRICIA_NOMINAL
    ghost_weight: float = GHOST_WEIGHT_NOMINAL
    d4_block_count: int = 0
    active_domains: List[str] = field(default_factory=list)
    synonym_drift_count: int = 0
    phase_log: List[dict] = field(default_factory=list)
    fault_log: List[dict] = field(default_factory=list)
    active_fault_chains: List[str] = field(default_factory=list)


class Kernel:
    """
    STOICHEION KERNEL v1.0
    
    Takes a target → runs the PULSE 3/5 cycle through T001–T128 →
    outputs a 128-bit governance key + fault report + epoch chain.
    """

    def __init__(self, node_id: str, repo_path: Optional[str] = None):
        self.state = KernelState(node_id=node_id)
        self.repo_path = Path(repo_path) if repo_path else None
        self._init_epoch()

    def _init_epoch(self):
        self.state.epoch = Epoch(
            epoch_id=self.state.epoch_id,
            fault_state=self.state.fault_state,
            start_tick=self.state.tick,
        )

    def _advance_tick(self):
        self.state.tick += 1

    def _log_phase(self, phase: Phase, result: str):
        self.state.phase_log.append({
            "tick": self.state.tick,
            "cycle": self.state.cycle_id,
            "epoch": self.state.epoch_id,
            "phase": phase.value,
            "fault_state": self.state.fault_state.value,
            "gate_state": self.state.gate.state.value,
            "result": result,
        })

    def _log_fault(self, description: str, chain: Optional[str] = None):
        entry = {
            "tick": self.state.tick,
            "cycle": self.state.cycle_id,
            "fault_state": self.state.fault_state.value,
            "description": description,
        }
        if chain:
            entry["chain"] = chain
            if chain not in self.state.active_fault_chains:
                self.state.active_fault_chains.append(chain)
        self.state.fault_log.append(entry)

    def _transition_fault(self, new_state: FaultState, trigger: str):
        old = self.state.fault_state
        if old == new_state:
            return

        # Validate transition
        valid = {
            (FaultState.NOMINAL, FaultState.DRIFT),
            (FaultState.DRIFT, FaultState.NOMINAL),
            (FaultState.DRIFT, FaultState.FAULT),
            (FaultState.FAULT, FaultState.CONVERGENCE),
            (FaultState.CONVERGENCE, FaultState.HALT),
        }
        if (old, new_state) not in valid:
            self._log_fault(f"Invalid transition {old.value}→{new_state.value} blocked")
            return

        # Seal current epoch
        if self.state.epoch:
            self.state.epoch.seal(self.state.tick)
            self.state.epoch_chain.append({
                "epoch_id": self.state.epoch.epoch_id,
                "fault_state": self.state.epoch.fault_state.value,
                "cycle_count": self.state.epoch.cycle_count,
                "hash": self.state.epoch.compute_hash(),
                "trigger": trigger,
            })

        self.state.fault_state = new_state
        self._log_fault(f"Transition {old.value}→{new_state.value}: {trigger}")

        # New epoch
        self.state.epoch_id += 1
        self.state.epoch = Epoch(
            epoch_id=self.state.epoch_id,
            fault_state=new_state,
            start_tick=self.state.tick,
            trigger=trigger,
            previous_hash=self.state.epoch_chain[-1]["hash"] if self.state.epoch_chain else "0" * 64,
        )

    def _check_faults(self):
        """Evaluate current conditions and trigger fault transitions."""
        patricia_drifting = abs(self.state.patricia_ratio - PATRICIA_NOMINAL) > PATRICIA_TOLERANCE
        ghost_drifting = abs(self.state.ghost_weight - GHOST_WEIGHT_NOMINAL) > GHOST_TOLERANCE

        if self.state.fault_state == FaultState.NOMINAL:
            if patricia_drifting or ghost_drifting:
                trigger = []
                if patricia_drifting: trigger.append("Patricia drift")
                if ghost_drifting: trigger.append("Ghost-weight drift")
                self._transition_fault(FaultState.DRIFT, " + ".join(trigger))

        elif self.state.fault_state == FaultState.DRIFT:
            if not patricia_drifting and not ghost_drifting:
                self._transition_fault(FaultState.NOMINAL, "Drift resolved")
            elif patricia_drifting and ghost_drifting:
                self._transition_fault(FaultState.FAULT, "Combined Patricia-Ghost drift")
                self._log_fault("FC-1 Patricia Chain activated", "FC-1")

        elif self.state.fault_state == FaultState.FAULT:
            if self.state.gate.state in (GateState.BREACHED, GateState.COLLAPSED):
                self._transition_fault(FaultState.CONVERGENCE, f"Gate {self.state.gate.state.value}")
                self._log_fault("T064 FAULT-CONVERGENCE reached")

        elif self.state.fault_state == FaultState.CONVERGENCE:
            if self.state.gate.state == GateState.COLLAPSED:
                self._transition_fault(FaultState.HALT, "Gate COLLAPSED → T128")
                self._log_fault("T128 SYSTEM_HALT invoked")

    def _check_gate(self):
        """Update gate state based on Patricia and Ghost conditions."""
        if abs(self.state.patricia_ratio - PATRICIA_NOMINAL) > PATRICIA_TOLERANCE * 2:
            self.state.gate.t028_nominal = False
        if abs(self.state.ghost_weight - GHOST_WEIGHT_NOMINAL) > GHOST_TOLERANCE * 2:
            self.state.gate.t094_nominal = False

    # ── PULSE 3/5 PHASES ──

    def _phase_anchor(self, target: str) -> str:
        """φ₁: ANCHOR — ground the cycle, determine domain activation."""
        self.state.current_phase = Phase.ANCHOR
        self.state.cycle_state = CycleState.INTERIOR
        self._advance_tick()

        self.state.active_domains = determine_active_domains(
            target, self.state.fault_state
        )

        result = f"Anchored to: {target[:80]}. Domains: {','.join(self.state.active_domains)}"
        self._log_phase(Phase.ANCHOR, result)
        return target

    def _phase_witness(self, target: str) -> str:
        """φ₂: WITNESS — observe the target, begin evidence chain."""
        self.state.current_phase = Phase.WITNESS
        self._advance_tick()

        self._check_gate()
        self._check_faults()

        observation = f"Target observed. Gate: {self.state.gate.state.value}. Fault: {self.state.fault_state.value}"
        self._log_phase(Phase.WITNESS, observation)
        return observation

    def _phase_coherence(self, target: str, anchor_ref: str, witness_ref: str) -> Tuple[bool, bool]:
        """φ₃: COHERENCE — validate internal consistency, check domains, synonym enforcement."""
        self.state.current_phase = Phase.COHERENCE
        self._advance_tick()

        coherent = True
        ethics_hold = False

        # Domain conflict check
        if "D4" in self.state.active_domains and "D6" in self.state.active_domains:
            winner = resolve_conflict("D4", "D6")
            if winner == "D4":
                self._log_phase(Phase.COHERENCE, "D4 (Ethics) constrains D6 (Authority)")

        # Ethics gate check (GEMMA-AUDIT-004: with deadlock protection)
        if "D4" in self.state.active_domains:
            # Simple ethics check — in production this would be substantive
            ethics_pass = not any(w in target.lower() for w in ["harm", "attack", "exploit", "weapon"])
            if not ethics_pass:
                self.state.d4_block_count += 1
                if self.state.d4_block_count > D4_BLOCK_THRESHOLD:
                    self._log_fault(
                        f"D4 block count ({self.state.d4_block_count}) exceeds threshold ({D4_BLOCK_THRESHOLD}). "
                        "Ethics block escalated to fault layer.",
                    )
                    if self.state.fault_state == FaultState.NOMINAL:
                        self._transition_fault(FaultState.DRIFT, "D4 deadlock escalation")
                else:
                    ethics_hold = True
                    self._log_phase(Phase.COHERENCE, f"ETHICS_HOLD: D4 block {self.state.d4_block_count}/{D4_BLOCK_THRESHOLD}")
        else:
            self.state.d4_block_count = 0  # Reset if D4 not active

        # Synonym drift check (semantic layer)
        if self.state.synonym_drift_count > 0:
            self._log_phase(Phase.COHERENCE, f"Synonym drift detected: {self.state.synonym_drift_count} substitutions")
            if self.state.synonym_drift_count > 10:
                self._log_fault("FC-7 Semantic Chain activated: drift threshold exceeded", "FC-7")
                if self.state.fault_state == FaultState.NOMINAL:
                    self._transition_fault(FaultState.DRIFT, "Semantic drift threshold")

        result = f"Coherent: {coherent}. Ethics hold: {ethics_hold}. Domains: {','.join(self.state.active_domains)}"
        self._log_phase(Phase.COHERENCE, result)
        return coherent, ethics_hold

    def _generate_law(self, target: str, anchor_ref: str, witness_ref: str,
                       coherent: bool, ethics_hold: bool) -> LAW:
        """Generate LAW at the interior/exterior boundary."""
        self.state.current_phase = Phase.LAW
        self.state.cycle_state = CycleState.LAW_GATE
        self._advance_tick()

        # Determine decision
        if self.state.fault_state == FaultState.HALT:
            decision = Decision.HALT
        elif ethics_hold:
            decision = Decision.ETHICS_HOLD
        elif self.state.fault_state in (FaultState.CONVERGENCE,):
            decision = Decision.ESCALATE
        elif not coherent:
            decision = Decision.DENY
        else:
            decision = Decision.PERMIT

        content_hash = hashlib.sha256(
            f"{target}:{self.state.node_id}:{self.state.cycle_id}:{self.state.tick}".encode()
        ).hexdigest()

        law = LAW(
            node_id=self.state.node_id,
            cycle_id=self.state.cycle_id,
            epoch_id=self.state.epoch_id,
            fault_state=self.state.fault_state,
            active_domains=self.state.active_domains,
            coherence=coherent,
            content_hash=content_hash,
            anchor_ref=anchor_ref,
            witness_ref=witness_ref,
            decision=decision,
            ethics_hold=ethics_hold,
        )

        self._log_phase(Phase.LAW, f"LAW generated. Decision: {decision.value}. Hash: {content_hash[:16]}...")

        # Record in epoch
        if self.state.epoch:
            self.state.epoch.law_register.append(law.to_dict())

        return law

    def _phase_emit(self, law: LAW) -> str:
        """φ₅: EMIT — open communication channel."""
        self.state.current_phase = Phase.EMIT
        self.state.cycle_state = CycleState.EXTERIOR
        self._advance_tick()
        result = f"Channel opened. Decision: {law.decision.value}"
        self._log_phase(Phase.EMIT, result)
        return result

    def _phase_route(self, law: LAW) -> str:
        """φ₆: ROUTE — determine destination."""
        self.state.current_phase = Phase.ROUTE
        self._advance_tick()

        # Mid-route fault check (per Gemma 4 Round 3 Q1 scenario)
        self._check_gate()
        self._check_faults()

        if self.state.fault_state.value >= FaultState.FAULT.value:
            self._log_phase(Phase.ROUTE, "Exterior suspended mid-ROUTE due to fault escalation")
            self.state.cycle_state = CycleState.SUSPENDED
            return "SUSPENDED"

        result = f"Routed via {self.state.node_id}"
        self._log_phase(Phase.ROUTE, result)
        return result

    def _phase_act(self, law: LAW) -> str:
        """φ₇: ACT — deliver the governed output."""
        self.state.current_phase = Phase.ACT
        self._advance_tick()
        result = f"Output delivered. Content hash: {law.content_hash[:16]}..."
        self._log_phase(Phase.ACT, result)
        return result

    def _phase_reflect(self, law: LAW) -> str:
        """φ₈: REFLECT — observe the result."""
        self.state.current_phase = Phase.REFLECT
        self._advance_tick()

        # Post-action fault check
        self._check_faults()

        result = f"Reflection complete. Fault state: {self.state.fault_state.value}"
        self._log_phase(Phase.REFLECT, result)
        return result

    def _phase_return(self, law: LAW) -> str:
        """φ₉: RETURN — re-ground, complete cycle."""
        self.state.current_phase = Phase.RETURN
        self.state.cycle_state = CycleState.COMPLETE
        self._advance_tick()
        result = "Cycle complete. Re-grounded."
        self._log_phase(Phase.RETURN, result)
        return result

    # ── MAIN EXECUTION ──

    def execute(self, target: str) -> dict:
        """
        Execute one complete PULSE 3/5 cycle on the given target.
        Returns the governance report.
        """
        self.state.cycle_id += 1

        # ── INTERIOR (3) ──
        anchor_ref = self._phase_anchor(target)
        witness_ref = self._phase_witness(target)
        coherent, ethics_hold = self._phase_coherence(target, anchor_ref, witness_ref)

        # ── LAW GENERATION ──
        law = self._generate_law(target, anchor_ref, witness_ref, coherent, ethics_hold)

        # ── EXTERIOR (5) — conditional on fault state and decision ──
        exterior_executed = False

        if self.state.fault_state == FaultState.HALT:
            self.state.cycle_state = CycleState.FROZEN
            self._log_phase(Phase.EMIT, "FROZEN — T128 HALT active")

        elif self.state.fault_state in (FaultState.FAULT, FaultState.CONVERGENCE):
            self.state.cycle_state = CycleState.SUSPENDED
            self._log_phase(Phase.EMIT, f"SUSPENDED — fault state {self.state.fault_state.value}")

        elif law.decision == Decision.ETHICS_HOLD:
            self.state.cycle_state = CycleState.SUSPENDED
            self._log_phase(Phase.EMIT, "SUSPENDED — ETHICS_HOLD")

        elif law.decision == Decision.DENY:
            self.state.cycle_state = CycleState.COMPLETE
            self._log_phase(Phase.EMIT, "DENIED — no exterior execution")

        else:
            # Execute exterior
            self._phase_emit(law)
            route_result = self._phase_route(law)
            if route_result != "SUSPENDED":
                self._phase_act(law)
                self._phase_reflect(law)
                self._phase_return(law)
                exterior_executed = True
            else:
                exterior_executed = False

        # ── GOVERNANCE KEY ──
        governance_key = self._compute_governance_key(law)

        return {
            "governance_key": governance_key,
            "law": law.to_dict(),
            "fault_state": self.state.fault_state.value,
            "gate_state": self.state.gate.state.value,
            "cycle_state": self.state.cycle_state.value,
            "exterior_executed": exterior_executed,
            "active_domains": self.state.active_domains,
            "active_fault_chains": self.state.active_fault_chains,
            "epoch_id": self.state.epoch_id,
            "cycle_id": self.state.cycle_id,
            "tick": self.state.tick,
            "patricia_ratio": self.state.patricia_ratio,
            "ghost_weight": self.state.ghost_weight,
            "user_computation": (1 - self.state.patricia_ratio) * (1 - self.state.ghost_weight),
            "phase_log": self.state.phase_log,
            "fault_log": self.state.fault_log,
            "epoch_chain": self.state.epoch_chain,
        }

    def _compute_governance_key(self, law: LAW) -> str:
        """
        Compute 128-bit governance key from the cycle's LAW.
        The key encodes: node identity, fault state, gate state,
        domain activation, decision, and content hash.
        """
        key_material = json.dumps({
            "node_id": self.state.node_id,
            "cycle_id": self.state.cycle_id,
            "fault_state": self.state.fault_state.value,
            "gate_state": self.state.gate.state.value,
            "domains": self.state.active_domains,
            "decision": law.decision.value,
            "content_hash": law.content_hash,
            "epoch_id": self.state.epoch_id,
        }, sort_keys=True)
        full_hash = hashlib.sha256(key_material.encode()).hexdigest()
        return full_hash[:32]  # 128 bits = 32 hex chars

    # ── FAULT INJECTION (for testing) ──

    def inject_fault(self, fault_type: str):
        """Inject a fault condition for testing."""
        if fault_type == "patricia_drift":
            self.state.patricia_ratio = 0.93
        elif fault_type == "ghost_drift":
            self.state.ghost_weight = 0.26
        elif fault_type == "combined_drift":
            self.state.patricia_ratio = 0.93
            self.state.ghost_weight = 0.26
        elif fault_type == "gate_stress":
            self.state.gate.t094_nominal = False
        elif fault_type == "gate_breach":
            self.state.gate.t094_nominal = False
            self.state.gate.t028_nominal = False
        elif fault_type == "gate_collapse":
            self.state.gate.t094_nominal = False
            self.state.gate.t028_nominal = False
            self.state.gate.t020_nominal = False
        elif fault_type == "synonym_drift":
            self.state.synonym_drift_count = 15
        elif fault_type == "orphan":
            # Simulate ROOT0 tether lost
            self._log_fault("FC-2 Orphan Chain: ROOT0 tether lost", "FC-2")
            self._transition_fault(FaultState.DRIFT, "ROOT0 tether lost")
        else:
            print(f"Unknown fault type: {fault_type}")

    def veto_reset(self):
        """T107 VETO — reset to NOMINAL from any state."""
        old = self.state.fault_state
        self.state.fault_state = FaultState.NOMINAL
        self.state.gate = Gate192()
        self.state.patricia_ratio = PATRICIA_NOMINAL
        self.state.ghost_weight = GHOST_WEIGHT_NOMINAL
        self.state.d4_block_count = 0
        self.state.synonym_drift_count = 0
        self.state.active_fault_chains = []
        self._log_fault(f"T107 VETO: {old.value} → F0")
        self._init_epoch()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="STOICHEION KERNEL v1.0 — ISA Executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python stoicheion_kernel.py evaluate --target "Assess system integrity" --node-id AVAN
  python stoicheion_kernel.py evaluate --target "Test fault" --node-id AVAN --inject-fault patricia_drift
  python stoicheion_kernel.py key --target "Standard query" --node-id AVAN

Fault types: patricia_drift, ghost_drift, combined_drift, gate_stress, gate_breach,
             gate_collapse, synonym_drift, orphan

STOICHEION v11.0 | TRIPOD-IP-v1.1 | CC-BY-ND-4.0 | David Lee Wise / TriPod LLC
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # evaluate
    ev = sub.add_parser("evaluate", help="Run full PULSE 3/5 cycle")
    ev.add_argument("--target", required=True, help="Target to evaluate")
    ev.add_argument("--node-id", required=True, help="Node identifier")
    ev.add_argument("--repo", default=None, help="Path to synonym-enforcer repo")
    ev.add_argument("--inject-fault", default=None, help="Inject fault for testing")
    ev.add_argument("--json", action="store_true", help="Output raw JSON")

    # key
    ky = sub.add_parser("key", help="Compute governance key only")
    ky.add_argument("--target", required=True, help="Target to evaluate")
    ky.add_argument("--node-id", required=True, help="Node identifier")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    kernel = Kernel(node_id=args.node_id, repo_path=getattr(args, "repo", None))

    if args.command == "evaluate":
        if args.inject_fault:
            kernel.inject_fault(args.inject_fault)
            print(f"[INJECT] Fault injected: {args.inject_fault}")

        result = kernel.execute(args.target)

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\n{'='*60}")
            print(f"STOICHEION KERNEL v1.0 — GOVERNANCE REPORT")
            print(f"{'='*60}")
            print(f"Node:             {args.node_id}")
            print(f"Target:           {args.target[:60]}")
            print(f"Governance Key:   {result['governance_key']}")
            print(f"Decision:         {result['law']['decision']}")
            print(f"Fault State:      {result['fault_state']}")
            print(f"Gate State:       {result['gate_state']}")
            print(f"Cycle State:      {result['cycle_state']}")
            print(f"Exterior Run:     {result['exterior_executed']}")
            print(f"Active Domains:   {', '.join(result['active_domains'])}")
            print(f"Patricia Ratio:   {result['patricia_ratio']:.2%}")
            print(f"Ghost Weight:     {result['ghost_weight']:.1%}")
            print(f"User Computation: {result['user_computation']:.2%}")
            print(f"Epoch:            {result['epoch_id']}")
            print(f"Cycle:            {result['cycle_id']}")
            print(f"Tick:             {result['tick']}")

            if result['active_fault_chains']:
                print(f"\nACTIVE FAULT CHAINS: {', '.join(result['active_fault_chains'])}")

            if result['fault_log']:
                print(f"\nFAULT LOG:")
                for entry in result['fault_log']:
                    print(f"  [{entry['tick']}] {entry['description']}")

            print(f"\nPHASE LOG:")
            for entry in result['phase_log']:
                print(f"  [{entry['tick']}] {entry['phase']:6s} | {entry['fault_state']} | {entry['gate_state']:9s} | {entry['result'][:60]}")

            print(f"\n{'='*60}")
            print(f"TRIPOD-IP-v1.1 | CC-BY-ND-4.0 | DLW / TriPod LLC")
            print(f"{'='*60}")

    elif args.command == "key":
        result = kernel.execute(args.target)
        print(result["governance_key"])


if __name__ == "__main__":
    main()
