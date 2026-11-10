"""A seeded protocol simulator; these scores do NOT measure general coding ability.

Ground truth is environment state, independent of the model and editable controller.
Hidden final seeds are evaluated only after selection, never sent to the proposer.
"""

import hashlib
import json
import random
from dataclasses import dataclass, field

ACTIONS = {0: "inspect", 1: "patch", 2: "test", 3: "finish", 4: "abort"}


@dataclass
class Workflow:
    transient_failures: int
    needs_second_patch: bool
    inspected: bool = False
    patched: bool = False
    verified: bool = False
    attempts: int = 0
    last_error: int = 0
    steps: int = 0
    done: bool = False
    success: bool = False
    trace: list = field(default_factory=list)
    budget: int = 12

    def observation(self):
        return [
            int(self.inspected),
            int(self.patched),
            int(self.verified),
            self.last_error,
            self.attempts,
            self.budget - self.steps,
            self.steps,
        ]

    def step(self, action):
        before = self.observation()
        self.steps += 1
        self.last_error = 0
        if action == 0:
            self.inspected = True
        elif action == 1:
            if not self.inspected:
                self.last_error = 1  # inspect required
            else:
                self.attempts += 1
                if self.attempts <= self.transient_failures:
                    self.last_error = 2  # transient failure, state unchanged
                else:
                    self.patched, self.verified = True, False
        elif action == 2:
            if not self.patched:
                self.last_error = 3  # nothing to test
            elif self.needs_second_patch:
                self.patched, self.needs_second_patch = False, False
                self.last_error = 4  # real regression; repair and retest
            else:
                self.verified = True
        elif action == 3:
            self.done = True
            self.success = self.inspected and self.patched and self.verified
        else:
            self.done = True
        self.trace.append({"state": before, "action": action, "error": self.last_error})
        if self.steps >= self.budget:
            self.done = True


def tasks(seed, count):
    rng = random.Random(seed)
    return [Workflow(rng.randrange(4), bool(rng.getrandbits(1))) for _ in range(count)]


def evaluate(controller, *, seed, count=64):
    records = []
    for index, env in enumerate(tasks(seed, count)):
        error = None
        while not env.done:
            try:
                a = controller.decide(env.observation())
            except Exception as exc:
                error = type(exc).__name__
                break
            env.step(a)
        records.append(
            {
                "task_id": f"{seed}:{index}",
                "success": env.success,
                "steps": env.steps,
                "controller_error": error,
                "trace": env.trace,
            }
        )
    solved = sum(r["success"] for r in records)
    return {
        "evaluation_type": "simulation_only",
        "suite": "repair-protocol-v1",
        "seed": seed,
        "count": count,
        "solved": solved,
        "success_rate": solved / count,
        "total_steps": sum(r["steps"] for r in records),
        "records": records,
    }


def summary(result):
    return {k: v for k, v in result.items() if k != "records"}


def failure_packet(result, limit=5):
    """Only development failures; no hidden seed, oracle code or hidden test cases."""
    return [r for r in result["records"] if not r["success"]][:limit]


def state_samples(seed=73, count=48):
    rng = random.Random(seed)
    states = [
        [a, b, c, e, n, 12 - k, k]
        for a in range(2)
        for b in range(2)
        for c in range(2)
        for e in range(5)
        for n, k in [(0, 0), (3, 7)]
    ]
    rng.shuffle(states)
    return states[:count]


def fingerprint(result):
    return hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
