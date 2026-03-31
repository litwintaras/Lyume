import pytest
from intent_classifier import classify_user_intent, classify_assistant_intent, is_noise


class TestUserIntent:
    def test_save_explicit_ukrainian(self):
        result = classify_user_intent("запам'ятай що мене звати Тарас")
        assert result["save"] is True
        assert "Тарас" in result["save_content"]

    def test_save_explicit_english(self):
        result = classify_user_intent("remember that I live in Berlin")
        assert result["save"] is True

    def test_forget_intent(self):
        result = classify_user_intent("забудь що я живу в Мюнхені")
        assert result["forget"] is True
        assert "Мюнхені" in result["forget_content"]

    def test_recall_intent(self):
        result = classify_user_intent("а ти пам'ятаєш де я працюю?")
        assert result["recall"] is True

    def test_negative_feedback(self):
        result = classify_user_intent("ні, не так, я мав на увазі інше")
        assert result["feedback"] == "negative"

    def test_positive_feedback(self):
        result = classify_user_intent("так, саме так, молодець")
        assert result["feedback"] == "positive"

    def test_farewell(self):
        result = classify_user_intent("добраніч, йду спати")
        assert result["farewell"] is True

    def test_no_intent(self):
        result = classify_user_intent("яка погода завтра?")
        assert result["save"] is False
        assert result["forget"] is False
        assert result["recall"] is False
        assert result["feedback"] is None
        assert result["farewell"] is False

    def test_fact_extraction_name(self):
        result = classify_user_intent("мене звати Тарас")
        assert result["save"] is True
        assert "Тарас" in result["save_content"]

    def test_fact_extraction_age(self):
        result = classify_user_intent("мені 28 років")
        assert result["save"] is True

    def test_fact_extraction_work(self):
        result = classify_user_intent("я працюю в Google")
        assert result["save"] is True


class TestAssistantIntent:
    def test_soft_save(self):
        result = classify_assistant_intent("Це важливо для мене, я це запам'ятовую.")
        assert result["save"] is True

    def test_soft_lesson(self):
        result = classify_assistant_intent("Я зрозуміла що наступного разу краще питати спочатку.")
        assert result["lesson"] is True

    def test_no_intent(self):
        result = classify_assistant_intent("Ось відповідь на твоє питання про Python.")
        assert result["save"] is False
        assert result["lesson"] is False

    def test_emotional_save(self):
        result = classify_assistant_intent("Дякую що ділишся, це зворушливо.")
        assert result["save"] is True

    def test_lesson_from_correction(self):
        result = classify_assistant_intent("Ой, я помилилась. Виправляюсь — правильно буде інакше.")
        assert result["lesson"] is True


class TestEdgeCases:
    def test_empty_string(self):
        result = classify_user_intent("")
        assert result["save"] is False
        assert result["feedback"] is None

    def test_forget_does_not_trigger_negative_feedback(self):
        result = classify_user_intent("забудь що я живу в Мюнхені")
        assert result["forget"] is True
        assert result["feedback"] is None  # not "negative"

    def test_mixed_language(self):
        result = classify_user_intent("запам'ятай that I live in Berlin")
        assert result["save"] is True

    def test_both_apostrophe_variants(self):
        r1 = classify_user_intent("запам'ятай це")
        r2 = classify_user_intent("запамʼятай це")
        assert r1["save"] is True
        assert r2["save"] is True


class TestIsNoise:
    """Noise filter: trivial messages that don't need memory search."""

    @pytest.mark.parametrize("text", [
        "ок", "окей", "okay", "ok",
        "так", "да", "yes", "yeah", "yep",
        "ні", "нет", "no", "nope",
        "привіт", "hello", "hi", "hey",
        "дякую", "thx", "thanks",
        "👍", "❤️", "🔥", "👌",
        ".", "...", "!", "?",
        "ну", "ага", "угу",
    ])
    def test_noise_detected(self, text):
        assert is_noise(text) is True, f"Should be noise: '{text}'"

    @pytest.mark.parametrize("text", [
        "запам'ятай що мене звати Тарас",
        "яка погода завтра в Берліні?",
        "розкажи про Python asyncio",
        "мене звати Тарас і мені 28 років",
        "я працюю в Google над AI проектом",
        "що ми робили минулий раз?",
        "добраніч, йду спати",
    ])
    def test_signal_not_filtered(self, text):
        assert is_noise(text) is False, f"Should NOT be noise: '{text}'"

    def test_short_gibberish_is_noise(self):
        assert is_noise("аа") is True
        assert is_noise("   ") is True

    def test_empty_is_noise(self):
        assert is_noise("") is True

    def test_short_with_uppercase_is_signal(self):
        """Short but capitalized words may be names/acronyms — signal."""
        assert is_noise("API") is False
        assert is_noise("Docker") is False

    def test_farewell_is_noise_lexically(self):
        """'бувай' matches NOISE_PATTERN, but farewell detection happens BEFORE noise check in proxy."""
        assert is_noise("бувай") is True
        assert is_noise("bye") is True
