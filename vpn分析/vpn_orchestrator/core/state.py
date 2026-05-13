"""VPN Orchestrator state machine."""

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
import time


class VpnState(Enum):
    DISCONNECTED = auto()   # sing-box not running
    CONNECTING = auto()     # sing-box starting, not yet verified
    CONNECTED = auto()      # sing-box running, proxy reachable
    DEGRADED = auto()       # sing-box running, proxy check failed
    SWITCHING = auto()      # mid node-switch
    RECOVERING = auto()     # cycling nodes to restore connectivity
    STOPPED = auto()        # deliberately stopped by user


TRANSITIONS = {
    VpnState.DISCONNECTED:  {VpnState.CONNECTING, VpnState.STOPPED},
    VpnState.CONNECTING:    {VpnState.CONNECTED, VpnState.DISCONNECTED, VpnState.STOPPED},
    VpnState.CONNECTED:     {VpnState.DEGRADED, VpnState.SWITCHING, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.DEGRADED:      {VpnState.RECOVERING, VpnState.CONNECTED, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.RECOVERING:    {VpnState.CONNECTED, VpnState.DEGRADED, VpnState.STOPPED, VpnState.DISCONNECTED},
    VpnState.SWITCHING:     {VpnState.CONNECTED, VpnState.DEGRADED, VpnState.STOPPED},
    VpnState.STOPPED:       {VpnState.CONNECTING, VpnState.DISCONNECTED},
}


@dataclass
class VpnStatus:
    state: VpnState = VpnState.DISCONNECTED
    current_node: Optional[str] = None           # remarks of active node
    last_check_ms: float = -1                     # last proxy latency
    consecutive_failures: int = 0
    total_switches: int = 0
    node_failures: dict = field(default_factory=dict)  # node_name -> failure count
    state_since: float = field(default_factory=time.monotonic)

    def reset_failures(self):
        self.consecutive_failures = 0
        self.node_failures.clear()

    def record_failure(self, node_name: str):
        self.consecutive_failures += 1
        self.node_failures[node_name] = self.node_failures.get(node_name, 0) + 1


class StateError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class StateMachine:
    def __init__(self):
        self._state = VpnState.DISCONNECTED

    @property
    def state(self) -> VpnState:
        return self._state

    def transition(self, to: VpnState) -> None:
        if to not in TRANSITIONS.get(self._state, set()):
            raise StateError(
                f"Illegal transition: {self._state.name} → {to.name}"
            )
        self._state = to

    def force(self, to: VpnState) -> None:
        """Bypass transition rules (use sparingly, e.g. for shutdown)."""
        self._state = to

    def in_state(self, *states: VpnState) -> bool:
        return self._state in states
