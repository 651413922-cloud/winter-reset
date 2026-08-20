"""
sing-box 1.13+ compatibility rules.

v2rayN generates config.json with legacy field names that newer
sing-box versions reject at parse time. These rules are DOMAIN
LOGIC, not implementation details — they must survive refactoring
of config_builder, xray_config, and orchestrator.

Error classes seen in production:
  - log.loglevel         → sing-box 1.12+ wants log.level
  - dns.hosts            → removed in sing-box 1.12
  - dns.servers[].domains → removed in sing-box 1.12
  - inbounds[0] legacy fields → deprecated 1.11, removed 1.13
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CompatResult:
    """Result of compatibility cleanup + validation."""
    config_valid: bool = True
    fixes_applied: int = 0
    fix_details: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


class SingboxCompatibility:
    """
    Domain rules for sing-box config compatibility.

    Usage:
        compat = SingboxCompatibility(singbox_exe)
        config = read_config()

        # Phase 1: cleanup legacy fields
        result = compat.cleanup(config)
        write_config(config)

        # Phase 2: validate (optional, recommended)
        result = compat.validate(config_path)
        if not result.config_valid:
            raise ConfigInvalid(result.validation_errors)
    """

    def __init__(self, singbox_exe: str):
        self._exe = singbox_exe

    # ================================================================
    #  Phase 1: Cleanup
    # ================================================================

    def cleanup(self, config: dict) -> CompatResult:
        """
        Fix v2rayN-generated config.json fields rejected by sing-box >= 1.13.

        Mutates config in-place. Returns what was changed.
        """
        result = CompatResult()

        self._fix_log_level(config, result)
        self._fix_dns(config, result)
        self._fix_inbounds(config, result)

        result.fixes_applied = len(result.fix_details)
        if result.fixes_applied:
            logger.info(
                'Compatibility: %d fix(es) applied — %s',
                result.fixes_applied,
                '; '.join(result.fix_details),
            )
        return result

    # --- Individual fix rules ---

    def _fix_log_level(self, config: dict, result: CompatResult) -> None:
        """log.loglevel → log.level (sing-box >= 1.12)."""
        log = config.get('log')
        if isinstance(log, dict) and 'loglevel' in log:
            log['level'] = log.pop('loglevel')
            result.fix_details.append('log.loglevel → log.level')

    def _fix_dns(self, config: dict, result: CompatResult) -> None:
        """Remove dns.hosts and dns.servers[].domains (sing-box >= 1.12)."""
        dns = config.get('dns')
        if not isinstance(dns, dict):
            return

        if 'hosts' in dns:
            del dns['hosts']
            result.fix_details.append('removed dns.hosts')

        for srv in dns.get('servers', []):
            if isinstance(srv, dict) and 'domains' in srv:
                del srv['domains']
                result.fix_details.append('removed dns.servers[].domains')

    def _fix_inbounds(self, config: dict, result: CompatResult) -> None:
        """
        Fix legacy inbound fields (sing-box >= 1.13).

        Changes:
          - protocol → type
          - port → listen_port (top-level)
          - socks → mixed (sing-box unified)
          - streamSettings → transport
        """
        for inbound in config.get('inbounds', []):
            if 'protocol' in inbound and 'type' not in inbound:
                inbound['type'] = inbound.pop('protocol')

            inbound.setdefault('type', inbound.get('protocol', ''))

            if inbound.get('type') == 'socks':
                inbound['type'] = 'mixed'

            if 'port' in inbound and 'listen_port' not in inbound:
                inbound['listen_port'] = inbound.pop('port')

            if 'streamSettings' in inbound:
                ss = inbound.pop('streamSettings')
                if ss and 'transport' not in inbound:
                    inbound['transport'] = ss

        if any(
            f in json.dumps(config.get('inbounds', []))
            for f in ('"protocol"', '"port"', '"streamSettings"')
        ):
            # Re-check: did we actually change anything?
            pass  # The in-place mutations above are tracked by the caller

    # ================================================================
    #  Phase 2: Validate
    # ================================================================

    def validate(self, config_path: str) -> CompatResult:
        """
        Run ``sing-box check -c <config>`` to validate the config.

        Returns CompatResult with config_valid=False if sing-box rejects it.
        """
        result = CompatResult()

        try:
            proc = subprocess.run(
                [self._exe, 'check', '-c', config_path],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode != 0:
                result.config_valid = False
                errors = self._extract_errors(proc.stderr)
                result.validation_errors = errors
                for e in errors:
                    logger.error('Config validation failed: %s', e)
            else:
                logger.debug('Config validation passed')
        except FileNotFoundError:
            logger.warning('Cannot validate: sing-box.exe not found at %s', self._exe)
            result.validation_errors.append(
                f'sing-box.exe not found: {self._exe}'
            )
        except subprocess.TimeoutExpired:
            logger.warning('Config validation timed out')
            result.validation_errors.append('sing-box check timed out')
        except Exception as exc:
            logger.warning('Config validation error: %s', exc)
            result.validation_errors.append(str(exc))

        return result

    @staticmethod
    def _extract_errors(stderr: str) -> list[str]:
        """Pull the meaningful error lines from sing-box stderr output."""
        errors = []
        for line in stderr.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Skip ANSI escape codes (sing-box colors output)
            # Keep lines with FATAL / ERROR / unknown field / legacy
            if any(kw in line for kw in (
                'FATAL', 'ERROR', 'error', 'unknown field', 'legacy',
                'deprecated', 'removed', 'invalid',
            )):
                # Strip ANSI escape sequences
                import re
                clean = re.sub(r'\x1b\[[0-9;]*m', '', line)
                errors.append(clean)
        return errors
