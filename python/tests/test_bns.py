import json
import pytest
from pathlib import Path
from pytest import approx

from bns import ChemicalState, BNSEngine, STIMULUS_MAP


# ChemicalState tests

class TestChemicalStateDefaults:
    def test_default_values(self):
        """Verify default chemical values."""
        state = ChemicalState()
        assert state.dopamine == 0.5
        assert state.serotonin == 0.5
        assert state.cortisol == 0.3
        assert state.oxytocin == 0.5


class TestChemicalStateDecay:
    def test_decay_toward_baseline(self, capsys):
        """After multiple decays, values converge to baseline."""
        state = ChemicalState(dopamine=0.8, serotonin=0.2, cortisol=0.7, oxytocin=0.9)

        for _ in range(100):
            state.decay(rate=0.95)

        assert state.dopamine == approx(0.5, abs=0.05)
        assert state.serotonin == approx(0.5, abs=0.05)
        assert state.cortisol == approx(0.3, abs=0.05)
        assert state.oxytocin == approx(0.5, abs=0.05)

    def test_decay_does_not_overshoot(self):
        """Decay from above/below baseline stays on same side."""
        # Above baseline
        state_high = ChemicalState(dopamine=0.8)
        initial_da = state_high.dopamine
        state_high.decay(rate=0.95)
        assert state_high.dopamine < initial_da  # decayed
        assert state_high.dopamine > 0.5  # but stays above baseline

        # Below baseline
        state_low = ChemicalState(dopamine=0.3)
        initial_da = state_low.dopamine
        state_low.decay(rate=0.95)
        assert state_low.dopamine > initial_da  # increased
        assert state_low.dopamine < 0.5  # but stays below baseline


class TestChemicalStateClamp:
    def test_clamp_limits(self):
        """Extreme values are clamped to limits."""
        state = ChemicalState(
            dopamine=1.0,  # max 0.85
            serotonin=-0.5,  # min 0.0
            cortisol=0.9,  # max 0.8
            oxytocin=1.5,  # max 0.9
        )
        state.clamp()

        assert state.dopamine == 0.85
        assert state.serotonin == 0.0
        assert state.cortisol == 0.8
        assert state.oxytocin == 0.9


class TestChemicalStateStimulus:
    def test_apply_stimulus_warm(self, capsys):
        """'warm' mood increases DA and OXT."""
        state = ChemicalState()
        initial_da = state.dopamine
        initial_oxt = state.oxytocin

        state.apply_stimulus("warm")

        assert state.dopamine == approx(initial_da + 0.10)
        assert state.oxytocin == approx(initial_oxt + 0.20)
        assert state.serotonin == 0.5  # unchanged

    def test_apply_stimulus_frustrated(self, capsys):
        """'frustrated' increases CORT, decreases 5-HT."""
        state = ChemicalState()
        initial_cort = state.cortisol
        initial_sert = state.serotonin

        state.apply_stimulus("frustrated")

        assert state.cortisol == approx(initial_cort + 0.15)
        assert state.serotonin == approx(initial_sert - 0.08)

    def test_apply_stimulus_none(self):
        """None mood does nothing."""
        state = ChemicalState()
        original = state.to_dict()

        state.apply_stimulus(None)

        assert state.to_dict() == original

    def test_apply_stimulus_unknown(self):
        """Unknown mood string does nothing."""
        state = ChemicalState()
        original = state.to_dict()

        state.apply_stimulus("unknown_mood_xyz")

        assert state.to_dict() == original


class TestChemicalStateEmotionalTone:
    def test_get_emotional_tone_high_cortisol(self):
        """CORT > 0.65 → 'тривожний, обережний'."""
        state = ChemicalState(cortisol=0.7)
        assert state.get_emotional_tone() == "тривожний, обережний"

    def test_get_emotional_tone_warm(self):
        """DA > 0.7 and OXT > 0.7 → 'теплий, ентузіазмований'."""
        state = ChemicalState(dopamine=0.75, oxytocin=0.75)
        assert state.get_emotional_tone() == "теплий, ентузіазмований"

    def test_get_emotional_tone_default(self):
        """Default values → 'нейтральний, зацікавлений'."""
        state = ChemicalState()  # DA=0.5, 5-HT=0.5, CORT=0.3, OXT=0.5
        assert state.get_emotional_tone() == "нейтральний, зацікавлений"

    def test_get_emotional_tone_high_serotonin(self):
        """5-HT > 0.7 → 'впевнений, спокійний'."""
        state = ChemicalState(serotonin=0.75)
        assert state.get_emotional_tone() == "впевнений, спокійний"

    def test_get_emotional_tone_high_dopamine(self):
        """DA > 0.65 (but not both DA and OXT) → 'цікавий, енергійний'."""
        state = ChemicalState(dopamine=0.7, oxytocin=0.5)
        assert state.get_emotional_tone() == "цікавий, енергійний"


class TestChemicalStateSpike:
    def test_has_spike_dopamine(self):
        """DA > 0.8 → spike detected."""
        state = ChemicalState(dopamine=0.82)
        spike = state.has_spike()
        assert spike is not None
        assert spike["chemical"] == "dopamine"
        assert spike["level"] == approx(0.82)

    def test_has_spike_cortisol(self):
        """CORT > 0.75 → spike detected."""
        state = ChemicalState(cortisol=0.78)
        spike = state.has_spike()
        assert spike is not None
        assert spike["chemical"] == "cortisol"
        assert spike["level"] == approx(0.78)

    def test_has_spike_none(self):
        """Normal values → no spike."""
        state = ChemicalState()  # DA=0.5, CORT=0.3
        spike = state.has_spike()
        assert spike is None

    def test_has_spike_dopamine_priority(self):
        """DA spike checked first."""
        state = ChemicalState(dopamine=0.82, cortisol=0.78)
        spike = state.has_spike()
        assert spike["chemical"] == "dopamine"


class TestChemicalStateSerialization:
    def test_to_dict_from_dict(self):
        """Round-trip serialization works."""
        original = ChemicalState(dopamine=0.6, serotonin=0.4, cortisol=0.5, oxytocin=0.7)

        data = original.to_dict()
        restored = ChemicalState.from_dict(data)

        assert restored.dopamine == original.dopamine
        assert restored.serotonin == original.serotonin
        assert restored.cortisol == original.cortisol
        assert restored.oxytocin == original.oxytocin

    def test_from_dict_missing_fields(self):
        """Missing fields use defaults."""
        partial_data = {"dopamine": 0.7}
        state = ChemicalState.from_dict(partial_data)

        assert state.dopamine == 0.7
        assert state.serotonin == 0.5
        assert state.cortisol == 0.3
        assert state.oxytocin == 0.5


# BNSEngine tests

class TestBNSEngineInitialization:
    def test_engine_creates_default_state(self, tmp_path):
        """New engine with non-existent path creates defaults."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))

        assert engine.state.dopamine == 0.5
        assert engine.state.serotonin == 0.5
        assert engine.state.cortisol == 0.3
        assert engine.state.oxytocin == 0.5


class TestBNSEnginePersistence:
    def test_engine_persistence(self, tmp_path):
        """State persists across engine instances."""
        state_file = tmp_path / "bns_state.json"

        # Create first engine and modify state
        engine1 = BNSEngine(str(state_file))
        engine1.state.dopamine = 0.75
        engine1._save_state()

        # Create second engine with same path
        engine2 = BNSEngine(str(state_file))
        assert engine2.state.dopamine == approx(0.75)


class TestBNSEngineProcessing:
    def test_process_input_mood(self, tmp_path):
        """process_input_mood applies full stimulus strength."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))
        initial_da = engine.state.dopamine

        engine.process_input_mood("excited")

        assert engine.state.dopamine == approx(initial_da + 0.15)

    def test_process_output_mood_half_strength(self, tmp_path):
        """process_output_mood applies 50% strength."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))
        initial_da = engine.state.dopamine
        initial_oxt = engine.state.oxytocin

        engine.process_output_mood("warm")

        # warm: DA +0.10, OXT +0.20 → at 50% = +0.05, +0.10
        assert engine.state.dopamine == approx(initial_da + 0.05)
        assert engine.state.oxytocin == approx(initial_oxt + 0.10)

    def test_process_output_mood_none(self, tmp_path):
        """process_output_mood with None does nothing."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))
        original = engine.state.to_dict()

        engine.process_output_mood(None)

        assert engine.state.to_dict() == original


class TestBNSEngineTick:
    def test_tick_applies_decay(self, tmp_path):
        """tick() applies decay."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))
        engine.state.dopamine = 0.8
        initial_da = engine.state.dopamine

        engine.tick()

        assert engine.state.dopamine < initial_da
        assert engine.state.dopamine > 0.5


class TestBNSEnginePromptInjection:
    def test_get_prompt_injection_format(self, tmp_path):
        """get_prompt_injection returns properly formatted text."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))

        injection = engine.get_prompt_injection()

        assert "<emotional_state>" in injection
        assert "</emotional_state>" in injection
        assert "Емоційний стан:" in injection
        assert "Рівні:" in injection
        assert f"DA={engine.state.dopamine:.2f}" in injection
        assert f"5-HT={engine.state.serotonin:.2f}" in injection
        assert f"CORT={engine.state.cortisol:.2f}" in injection
        assert f"OXT={engine.state.oxytocin:.2f}" in injection

    def test_get_prompt_injection_with_different_states(self, tmp_path):
        """prompt injection reflects current emotional state."""
        state_file = tmp_path / "bns_state.json"
        engine = BNSEngine(str(state_file))

        # Default state
        injection1 = engine.get_prompt_injection()
        assert "нейтральний, зацікавлений" in injection1

        # High cortisol
        engine.state.cortisol = 0.7
        injection2 = engine.get_prompt_injection()
        assert "тривожний, обережний" in injection2
