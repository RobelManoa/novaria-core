"""Contrôleur de feux simulé d'un carrefour : machine à états et garde-fous (MS-12).

Domaine pur : l'heure arrive en paramètre (`now`), rien n'est lu ni écrit ailleurs. Un contrôleur
n'est pas thread-safe ; `services/signals.py` le protège par un verrou.

**Cycle.** Les phases (`P1` nord-sud, `P2` est-ouest par défaut) se suivent dans l'ordre. Chaque
phase dure `duration_s` et **finit par `ALL_RED_S` secondes de dégagement** (tout est au rouge) : on
ne passe jamais d'un vert à un vert qui le croise. La durée d'une phase compte donc son dégagement,
comme le
`webster.py` du traitement.

**Modes.**

| Mode | Quand | Plan appliqué |
|---|---|---|
| `DEGRADED_FIXED_PLAN` | au démarrage, et sans recommandation valable | durées fixes |
| `AUTOMATIC` | une recommandation sûre a été reçue | ses durées, jusqu'à sa péremption |
| `MANUAL` | un opérateur tient une phase | la phase tenue, pour la durée demandée |

**Ce que le contrôleur ne fait jamais.** Couper une phase sous `MIN_PHASE_S`, enchaîner deux phases
sans dégagement, changer les approches au vert d'une phase en cours, appliquer un plan que
`safety.check_plan` refuse, accepter une seconde commande manuelle pendant la première.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import Action, Command, Decision, Mode, Origin, Outcome, Provenance
from .safety import (
    ALL_RED_S,
    MIN_PHASE_S,
    Layout,
    Phase,
    Violation,
    check_duration,
    check_plan,
    validate_layout,
)

UNKNOWN_PHASE = "UNKNOWN_PHASE"
MIN_DURATION_NOT_ELAPSED = "MIN_DURATION_NOT_ELAPSED"
CLEARANCE_IN_PROGRESS = "CLEARANCE_IN_PROGRESS"
COMMAND_IN_PROGRESS = "COMMAND_IN_PROGRESS"
MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

SEEN_RECOMMENDATIONS = 64  # identifiants retenus pour reconnaître une recommandation rejouée


@dataclass
class Running:
    """La phase en cours : de `started_at` à `ends_at`, dégagement compris."""

    phase_id: str
    started_at: datetime
    ends_at: datetime
    hold: bool = False  # tenue par une commande manuelle


@dataclass(frozen=True)
class Forced:
    """Phase imposée, qui démarre quand la phase en cours a fini son dégagement."""

    phase_id: str
    duration_s: int


@dataclass(frozen=True)
class StateView:
    """L'état du carrefour à un instant, tel que l'API et `signal.status` le disent."""

    intersection_id: str
    mode: Mode
    phase_id: str
    phase_started_at: datetime
    phase_ends_at: datetime
    signal: str  # GREEN, ou ALL_RED pendant le dégagement
    green_approaches: tuple[str, ...]  # vide pendant le dégagement
    phases: tuple[Phase, ...]
    decision: Decision
    updated_at: datetime
    provenance: Provenance


def _refuse(origin: Origin, reference: str | None, violations: list[Violation]) -> Decision:
    return Decision(
        origin,
        reference,
        Outcome.REFUSED,
        refusal_reason=violations[0].code,
        detail="; ".join(v.message for v in violations),
        reasons=tuple(v.code for v in violations),
        changed=False,
    )


class SignalController:
    def __init__(
        self,
        intersection_id: str,
        layout: Layout,
        fixed_phase_s: int,
        now: datetime,
        provenance: Provenance,
        *,
        max_silence_s: int,
    ) -> None:
        validate_layout(layout)
        problem = check_duration(fixed_phase_s)
        if problem:
            raise ValueError(f"plan fixe : {problem.message}")
        self.intersection_id = intersection_id
        self.layout = layout
        self._order = [phase_id for phase_id, _ in layout]
        self._approaches = dict(layout)
        self.fixed = dict.fromkeys(self._order, fixed_phase_s)
        self.durations = dict(self.fixed)
        self.max_silence_s = max_silence_s
        self.mode = Mode.DEGRADED_FIXED_PLAN
        self.provenance = provenance
        self.running = Running(self._order[0], now, now + timedelta(seconds=fixed_phase_s))
        self.forced: Forced | None = None
        self.hold_command: str | None = None  # la commande manuelle en cours
        self.automatic_until: datetime | None = None  # au-delà, retour au plan fixe
        self._last_recommendation_time: datetime | None = None
        self._seen: deque[str] = deque(maxlen=SEEN_RECOMMENDATIONS)
        self.last_decision = Decision(Origin.STARTUP, None, Outcome.APPLIED)
        self.updated_at = now

    # ------------------------------------------------------------------ lecture
    def view(self, now: datetime) -> StateView:
        run = self.running
        green = now < run.ends_at - timedelta(seconds=ALL_RED_S)
        return StateView(
            intersection_id=self.intersection_id,
            mode=self.mode,
            phase_id=run.phase_id,
            phase_started_at=run.started_at,
            phase_ends_at=run.ends_at,
            signal="GREEN" if green else "ALL_RED",
            green_approaches=self._approaches[run.phase_id] if green else (),
            phases=tuple(
                Phase(phase_id, approaches, self.durations[phase_id])
                for phase_id, approaches in self.layout
            ),
            decision=self.last_decision,
            updated_at=self.updated_at,
            provenance=self.provenance,
        )

    def _in_green(self, now: datetime) -> bool:
        return now < self.running.ends_at - timedelta(seconds=ALL_RED_S)

    # ------------------------------------------------------------------ le temps passe
    def tick(self, now: datetime) -> list[Decision]:
        """Fait avancer les phases ; rend les décisions prises par le seul passage du temps."""
        decisions = self._advance(now)
        if self.mode is Mode.AUTOMATIC and self.automatic_until and now >= self.automatic_until:
            decisions.append(self._fall_back(now))
        return decisions

    def _advance(self, now: datetime) -> list[Decision]:
        decisions: list[Decision] = []
        while now >= self.running.ends_at:
            done = self.running
            at = done.ends_at
            if done.hold and self.hold_command is not None:
                decisions.append(self._hold_ended(at))
            phase_id, duration_s, hold = self._next(done)
            self.running = Running(phase_id, at, at + timedelta(seconds=duration_s), hold)
        return decisions

    def _next(self, done: Running) -> tuple[str, int, bool]:
        if self.forced is not None:
            forced, self.forced = self.forced, None
            return forced.phase_id, forced.duration_s, True
        following = self._order[(self._order.index(done.phase_id) + 1) % len(self._order)]
        return following, self.durations[following], False

    def _hold_ended(self, at: datetime) -> Decision:
        command_id, self.hold_command = self.hold_command, None
        if self.automatic_until and at < self.automatic_until:
            self.mode = Mode.AUTOMATIC
            return self._remember(Decision(Origin.MANUAL_COMMAND, command_id, Outcome.APPLIED), at)
        return self._fall_back(at, running=False)

    def _fall_back(self, now: datetime, *, running: bool = True) -> Decision:
        """Retour au plan à durées fixes : recommandation périmée, ou fin de commande manuelle."""
        self.mode = Mode.DEGRADED_FIXED_PLAN
        self.automatic_until = None
        self.durations = dict(self.fixed)
        if running:
            self._retime(now)
        return self._remember(Decision(Origin.FIXED_PLAN_FALLBACK, None, Outcome.APPLIED), now)

    def stop(self, now: datetime) -> Decision | None:
        """Arrêt du service : tout revient au plan fixe, commande manuelle comprise.

        Rend `None` si le contrôleur était déjà au plan fixe, sans rien à lâcher.
        """
        if self.mode is Mode.DEGRADED_FIXED_PLAN and self.hold_command is None:
            return None
        self.hold_command = None
        self.forced = None
        self.running.hold = False
        return self._fall_back(now)

    def _remember(self, decision: Decision, at: datetime) -> Decision:
        self.last_decision = decision
        self.updated_at = at
        return decision

    def _retime(self, now: datetime) -> None:
        """Applique les durées courantes à la phase en cours, sans jamais la couper trop court.

        Une phase déjà au dégagement, tenue par un opérateur ou suivie d'une phase imposée, ne
        bouge pas. Sinon sa fin devient `début + durée`, mais jamais avant `MIN_PHASE_S` écoulées
        ni avant `ALL_RED_S` secondes de dégagement.
        """
        run = self.running
        if run.hold or self.forced is not None or not self._in_green(now):
            return
        target = run.started_at + timedelta(seconds=self.durations[run.phase_id])
        floor = max(
            run.started_at + timedelta(seconds=MIN_PHASE_S), now + timedelta(seconds=ALL_RED_S)
        )
        run.ends_at = max(target, floor)

    # ------------------------------------------------------------------ une recommandation
    def on_recommendation(
        self,
        recommendation_id: str,
        recommendation_time: datetime,
        phases: list[Phase],
        cycle_s: int,
        validity_s: float,
        provenance: Provenance,
        now: datetime,
    ) -> Decision | None:
        """`None` : rejouée, plus ancienne que la dernière ou déjà périmée : rien à dire."""
        if recommendation_id in self._seen:
            return None
        if self._last_recommendation_time and recommendation_time <= self._last_recommendation_time:
            return None
        if validity_s <= 0:
            return None
        self._seen.append(recommendation_id)
        self._last_recommendation_time = recommendation_time
        self.provenance = provenance
        violations = check_plan(phases, cycle_s, self.layout)
        if not violations and self.mode is Mode.MANUAL:
            violations = [
                Violation(
                    MANUAL_OVERRIDE, "une commande manuelle est en cours : elle est prioritaire"
                )
            ]
        if violations:
            return self._remember(
                _refuse(Origin.RECOMMENDATION, recommendation_id, violations), now
            )
        self.mode = Mode.AUTOMATIC
        self.automatic_until = now + timedelta(seconds=min(validity_s, self.max_silence_s))
        self.durations = {phase.phase_id: phase.duration_s for phase in phases}
        self._retime(now)
        return self._remember(
            Decision(Origin.RECOMMENDATION, recommendation_id, Outcome.APPLIED), now
        )

    # ------------------------------------------------------------------ une commande manuelle
    def on_command(self, command: Command, now: datetime) -> Decision:
        if command.action is Action.RESUME_AUTOMATIC:
            return self._resume(command, now)
        return self._set_phase(command, now)

    @staticmethod
    def _refused(command: Command, code: str, message: str, _now: datetime) -> Decision:
        # L'état courant, avec sa dernière décision, reste celui du contrôleur.
        return _refuse(Origin.MANUAL_COMMAND, command.command_id, [Violation(code, message)])

    def _set_phase(self, command: Command, now: datetime) -> Decision:
        run = self.running
        if command.phase_id not in self._approaches:
            return self._refused(
                command, UNKNOWN_PHASE, "cette phase n'existe pas sur ce carrefour", now
            )
        duration_s = command.duration_s or 0
        problem = check_duration(duration_s)
        if problem:
            return self._refused(command, problem.code, problem.message, now)
        if self.hold_command is not None:
            return self._refused(
                command, COMMAND_IN_PROGRESS, "une commande manuelle est déjà en cours", now
            )
        if self.forced is not None or not self._in_green(now):
            return self._refused(
                command,
                CLEARANCE_IN_PROGRESS,
                "dégagement en cours : réessayer à la phase suivante",
                now,
            )
        if command.phase_id == run.phase_id:
            run.ends_at = now + timedelta(seconds=duration_s)
            run.hold = True
        else:
            if (now - run.started_at).total_seconds() < MIN_PHASE_S:
                return self._refused(
                    command,
                    MIN_DURATION_NOT_ELAPSED,
                    f"la phase en cours n'a pas encore duré {MIN_PHASE_S} s",
                    now,
                )
            run.ends_at = now + timedelta(seconds=ALL_RED_S)
            self.forced = Forced(command.phase_id, duration_s)
        self.hold_command = command.command_id
        self.mode = Mode.MANUAL
        return self._remember(
            Decision(Origin.MANUAL_COMMAND, command.command_id, Outcome.APPLIED), now
        )

    def _resume(self, command: Command, now: datetime) -> Decision:
        if self.hold_command is None:
            return Decision(
                Origin.MANUAL_COMMAND,
                command.command_id,
                Outcome.APPLIED,
                detail="aucune commande manuelle en cours",
                changed=False,
            )
        run = self.running
        if self.forced is not None:
            return self._refused(
                command, CLEARANCE_IN_PROGRESS, "la phase imposée n'a pas encore démarré", now
            )
        if self._in_green(now):
            if (now - run.started_at).total_seconds() < MIN_PHASE_S:
                return self._refused(
                    command,
                    MIN_DURATION_NOT_ELAPSED,
                    f"la phase tenue n'a pas encore duré {MIN_PHASE_S} s",
                    now,
                )
            run.ends_at = now + timedelta(seconds=ALL_RED_S)
        run.hold = False
        self.hold_command = None
        if self.automatic_until and now < self.automatic_until:
            self.mode = Mode.AUTOMATIC
        else:
            self.mode = Mode.DEGRADED_FIXED_PLAN
            self.automatic_until = None
            self.durations = dict(self.fixed)
        return self._remember(
            Decision(Origin.MANUAL_COMMAND, command.command_id, Outcome.APPLIED), now
        )
