from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path


CLAMP_LIMITS = {
    "dopamine": (0.0, 0.85),
    "serotonin": (0.0, 0.85),
    "cortisol": (0.0, 0.8),
    "oxytocin": (0.0, 0.9),
}

STIMULUS_MAP: dict[str, dict[str, float]] = {
    "warm": {"dopamine": +0.10, "oxytocin": +0.20},
    "happy": {"dopamine": +0.10, "serotonin": +0.05},
    "excited": {"dopamine": +0.15},
    "approval": {"serotonin": +0.10, "oxytocin": +0.10, "cortisol": -0.05},
    "fun": {"dopamine": +0.10},
    "cool": {"dopamine": +0.05, "serotonin": +0.05},
    "frustrated": {"cortisol": +0.15, "serotonin": -0.08},
    "angry": {"cortisol": +0.20, "serotonin": -0.10, "dopamine": -0.05},
    "sad": {"cortisol": +0.10, "dopamine": -0.10, "oxytocin": +0.05},
    "confused": {"cortisol": +0.08, "serotonin": -0.05},
    "thinking": {"dopamine": +0.05},
    "ironic": {"dopamine": +0.03},
    "awkward": {"cortisol": +0.05},
    "passionate": {"dopamine": +0.10, "oxytocin": +0.05},
}


@dataclass
class ChemicalState:
    dopamine: float = 0.5
    serotonin: float = 0.5
    cortisol: float = 0.3
    oxytocin: float = 0.5

    def decay(self, rate: float = 0.95):
        """Chemicals decay toward baseline over time."""
        baselines = {"dopamine": 0.5, "serotonin": 0.5, "cortisol": 0.3, "oxytocin": 0.5}
        for chem, baseline in baselines.items():
            current = getattr(self, chem)
            decayed = baseline + (current - baseline) * rate
            setattr(self, chem, decayed)
        print(f"[bns] decay: DA={self.dopamine:.2f} 5-HT={self.serotonin:.2f} CORT={self.cortisol:.2f} OXT={self.oxytocin:.2f}")

    def clamp(self):
        """Circuit breaker — prevent chemical overflow."""
        for chem, (min_val, max_val) in CLAMP_LIMITS.items():
            current = getattr(self, chem)
            clamped = max(min_val, min(max_val, current))
            setattr(self, chem, clamped)
        print(f"[bns] clamp: DA={self.dopamine:.2f} 5-HT={self.serotonin:.2f} CORT={self.cortisol:.2f} OXT={self.oxytocin:.2f}")

    def apply_stimulus(self, mood: str | None):
        """Apply mood-based chemical delta, then clamp."""
        if mood is None or mood not in STIMULUS_MAP:
            return

        delta = STIMULUS_MAP[mood]
        for chem, change in delta.items():
            current = getattr(self, chem)
            setattr(self, chem, current + change)

        self.clamp()
        print(f"[bns] stimulus '{mood}': DA={self.dopamine:.2f} 5-HT={self.serotonin:.2f} CORT={self.cortisol:.2f} OXT={self.oxytocin:.2f}")

    def get_emotional_tone(self) -> str:
        """Generate emotional tone description for LLM prompt injection."""
        if self.cortisol > 0.65:
            return "тривожний, обережний"
        elif self.dopamine > 0.7 and self.oxytocin > 0.7:
            return "теплий, ентузіазмований"
        elif self.serotonin > 0.7:
            return "впевнений, спокійний"
        elif self.dopamine > 0.65:
            return "цікавий, енергійний"
        elif self.oxytocin > 0.65:
            return "теплий, уважний"
        elif self.cortisol > 0.5:
            return "зосереджений, трохи напружений"
        else:
            return "нейтральний, зацікавлений"

    def has_spike(self) -> dict | None:
        """Return spike info if any chemical exceeds threshold, else None."""
        if self.dopamine > 0.8:
            return {"chemical": "dopamine", "level": self.dopamine}
        elif self.cortisol > 0.75:
            return {"chemical": "cortisol", "level": self.cortisol}
        return None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "dopamine": self.dopamine,
            "serotonin": self.serotonin,
            "cortisol": self.cortisol,
            "oxytocin": self.oxytocin,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ChemicalState:
        """Deserialize from dict."""
        return cls(
            dopamine=data.get("dopamine", 0.5),
            serotonin=data.get("serotonin", 0.5),
            cortisol=data.get("cortisol", 0.3),
            oxytocin=data.get("oxytocin", 0.5),
        )


class BNSEngine:
    def __init__(self, state_path: str = "bns_state.json"):
        self._state_path = state_path
        self.state = self._load_state(state_path)
        print(f"[bns] initialized with state file: {state_path}")

    def process_input_mood(self, mood: str | None):
        """Update chemicals based on user input mood."""
        if mood:
            print(f"[bns] processing input mood: {mood}")
            self.state.apply_stimulus(mood)
            self._save_state()

    def process_output_mood(self, mood: str | None):
        """Update chemicals based on assistant response mood (50% strength feedback)."""
        if mood is None or mood not in STIMULUS_MAP:
            return

        print(f"[bns] processing output mood (50% strength): {mood}")
        delta = STIMULUS_MAP[mood]

        for chem, change in delta.items():
            current = getattr(self.state, chem)
            setattr(self.state, chem, current + change * 0.5)

        self.state.clamp()
        self._save_state()

    def tick(self):
        """Called periodically — apply decay."""
        self.state.decay()
        self._save_state()

    def get_prompt_injection(self) -> str:
        """Return the text to inject into system prompt."""
        tone = self.state.get_emotional_tone()
        levels = f"DA={self.state.dopamine:.2f} 5-HT={self.state.serotonin:.2f} CORT={self.state.cortisol:.2f} OXT={self.state.oxytocin:.2f}"
        return f"<emotional_state>\nЕмоційний стан: {tone}\nРівні: {levels}\nВідповідай відповідно до свого емоційного стану.\n</emotional_state>"

    def _load_state(self, path: str) -> ChemicalState:
        """Load state from JSON file, or create default."""
        state_path = Path(path)
        if state_path.exists():
            try:
                with open(state_path, "r") as f:
                    data = json.load(f)
                    print(f"[bns] loaded state from {path}")
                    return ChemicalState.from_dict(data)
            except Exception as e:
                print(f"[bns] error loading state: {e}, using defaults")
        else:
            print(f"[bns] state file {path} not found, creating new")
        return ChemicalState()

    def _save_state(self):
        """Save state to JSON file."""
        try:
            state_path = Path(self._state_path)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path, "w") as f:
                json.dump(self.state.to_dict(), f, indent=2)
            print(f"[bns] saved state to {self._state_path}")
        except Exception as e:
            print(f"[bns] error saving state: {e}")


if __name__ == "__main__":
    engine = BNSEngine("/tmp/bns_test.json")

    print("\n=== Testing stimulus application ===")
    engine.process_input_mood("excited")
    engine.process_input_mood("happy")

    print("\n=== Testing output mood (50% strength) ===")
    engine.process_output_mood("warm")

    print("\n=== Testing decay ===")
    engine.tick()

    print("\n=== Testing emotional tone ===")
    print(f"Tone: {engine.state.get_emotional_tone()}")

    print("\n=== Testing spike detection ===")
    spike = engine.state.has_spike()
    print(f"Spike: {spike}")

    print("\n=== Testing prompt injection ===")
    print(engine.get_prompt_injection())
