"""VPN Orchestrator state machine."""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import time


class VpnState(Enum):
    """VPN lifecycle states."""
    DISCONNECTED = auto()   # sing-box not running
    CONNECTING = auto()     # sing-box starting, not yet verified
    CONNECTED = auto()      # sing-box running, proxy reachable
    DEGRADED = auto()       # sing-box running, proxy check failed (transient)
    FAILED = auto()         # all recovery attempts exhausted
    SWITCHING = auto()      # mid node-switch
    RECOVERING = auto()     # cycling nodes to restore connectivity
    STOPPED = auto()        # deliberately stopped by user


# Valid transitions: from_state → {to_states}
TRANSITIONS: Dict[VpnState, set] = {
    VpnState.DISCONNECTED:  {VpnState.CONNECTING, VpnState.STOPPED},
    VpnState.CONNECTING:    {VpnState.CONNECTED, VpnState.DISCONNECTED, VpnState.FAILED, VpnState.STOPPED},
    VpnState.CONNECTED:     {VpnState.DEGRADED, VpnState.SWITCHING, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.DEGRADED:      {VpnState.RECOVERING, VpnState.CONNECTED, VpnState.FAILED, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.FAILED:        {VpnState.RECOVERING, VpnState.CONNECTING, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.RECOVERING:    {VpnState.CONNECTED, VpnState.DEGRADED, VpnState.FAILED, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.SWITCHING:     {VpnState.CONNECTED, VpnState.DEGRADED, VpnState.FAILED, VpnState.STOPPED},
    VpnState.STOPPED:       {VpnState.CONNECTING, VpnState.DISCONNECTED},
}


# Terminal / stable states (no auto-recovery attempted)
STABLE_STATES = {VpnState.CONNECTED, VpnState.STOPPED}

# States where auto-recovery should be attempted
UNHEALTHY_STATES = {VpnState.DEGRADED, VpnState.FAILED, VpnState.DISCONNECTED}


class RecoveryStrategy(Enum):
    """Ordered recovery strategies for auto-healing."""
    RESTART_PROCESS = auto()    # Restart sing-box with same node
    SWITCH_NODE = auto()        # Try next best node
    RESET_CONFIG = auto()       # Restore config.json from backup
    WAIT_RETRY = auto()         # Back off and retry later
    GIVE_UP = auto()            # All strategies exhausted


# Recovery escalation: consecutive_failures → strategy
# Thresholds are tuned for daemon mode (30s tick interval)
RECOVERY_ESCALATION: List[tuple] = [
    (0,  RecoveryStrategy.RESTART_PROCESS),   # failure 1-2: restart
    (3,  RecoveryStrategy.SWITCH_NODE),        # failure 3-5: switch node
    (6,  RecoveryStrategy.RESET_CONFIG),       # failure 6-8: restore config
    (9,  RecoveryStrategy.WAIT_RETRY),         # failure 9+: back off
    (15, RecoveryStrategy.GIVE_UP),            # failure 15+: enter FAILED
]


@dataclass
class HealthSnapshot:
    """Health check result."""
    online: bool = False
    latency_ms: float = -1.0
    speed_mb_s: float = 0.0
    process_running: bool = False
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def is_healthy(self) -> bool:
        return self.online and self.process_running

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.timestamp


@dataclass
class VpnStatus:
    """Mutable VPN operational state (separate from state machine)."""
    state: VpnState = VpnState.DISCONNECTED
    current_node: Optional[str] = None           # remarks of active node
    current_node_index_id: Optional[str] = None  # DB IndexId
    last_health: HealthSnapshot = field(default_factory=HealthSnapshot)
    consecutive_failures: int = 0
    total_switches: int = 0
    node_failures: Dict[str, int] = field(default_factory=dict)  # node_name → count
    state_since: float = field(default_factory=time.monotonic)
    last_recovery_at: float = 0.0
    recovery_attempts: int = 0

    def reset_failures(self):
        self.consecutive_failures = 0
        self.recovery_attempts = 0

    def record_failure(self, node_name: str):
        self.consecutive_failures += 1
        self.node_failures[node_name] = self.node_failures.get(node_name, 0) + 1

    def update_health(self, online: bool, latency_ms: float,
                      process_running: bool, speed_mb_s: float = 0.0):
        self.last_health = HealthSnapshot(
            online=online,
            latency_ms=latency_ms,
            speed_mb_s=speed_mb_s,
            process_running=process_running,
        )

    def get_recovery_strategy(self) -> RecoveryStrategy:
        """Determine recovery strategy based on consecutive failures."""
        strategy = RecoveryStrategy.RESTART_PROCESS
        for threshold, strat in RECOVERY_ESCALATION:
            if self.consecutive_failures >= threshold:
                strategy = strat
        return strategy

    @property
    def state_duration_seconds(self) -> float:
        return time.monotonic() - self.state_since

    def is_node_blacklisted(self, node_name: str, max_failures: int = 3) -> bool:
        """Check if a node has failed too many times in this session."""
        return self.node_failures.get(node_name, 0) >= max_failures


class StateError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class StateMachine:
    """VPN state machine with strict transition validation."""

    def __init__(self):
        self._state = VpnState.DISCONNECTED
        self._history: List[tuple] = []  # (from_state, to_state, timestamp)

    @property
    def state(self) -> VpnState:
        return self._state

    @property
    def is_stable(self) -> bool:
        return self._state in STABLE_STATES

    @property
    def is_unhealthy(self) -> bool:
        return self._state in UNHEALTHY_STATES

    def transition(self, to: VpnState) -> None:
        """Attempt a state transition. Raises StateError if invalid."""
        if to not in TRANSITIONS.get(self._state, set()):
            raise StateError(
                f"Illegal transition: {self._state.name} → {to.name}"
            )
        self._history.append((self._state, to, time.monotonic()))
        self._state = to

    def transition_if_valid(self, to: VpnState) -> bool:
        """Try a transition, return False instead of raising on invalid."""
        try:
            self.transition(to)
            return True
        except StateError:
            return False

    def force(self, to: VpnState) -> None:
        """Bypass transition rules (use for shutdown, initial sync)."""
        self._history.append((self._state, to, time.monotonic()))
        self._state = to

    def in_state(self, *states: VpnState) -> bool:
        return self._state in states

    def last_transition(self) -> Optional[tuple]:
        return self._history[-1] if self._history else None
