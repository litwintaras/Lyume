import re


# --- User intent patterns ---

SAVE_INTENT = re.compile(
    r"запам['\ʼ]ятай|запиши|збережи|не забудь|нагадай мені|remember",
    re.IGNORECASE,
)

FACT_PATTERNS = [
    re.compile(r"(мо[гєї]\w*\s+\w+\s+звати\s+.+)", re.IGNORECASE),
    re.compile(r"(мене звати\s+.+)", re.IGNORECASE),
    re.compile(r"(мій\s+.+)", re.IGNORECASE),
    re.compile(r"(я живу\s+.+)", re.IGNORECASE),
    re.compile(r"(я працюю\s+.+)", re.IGNORECASE),
    re.compile(r"(мені\s+\d+\s+років)", re.IGNORECASE),
    re.compile(r"(?:запам['\ʼ]ятай|запиши|збережи|не забудь|нагадай мені|remember)[,:]?\s*(.+)", re.IGNORECASE),
]

FORGET_INTENT = re.compile(
    r"забудь|видали|прибери з пам[ʼ']ят|зітри|delete|forget|remove from memory",
    re.IGNORECASE,
)

RECALL_INTENT = re.compile(
    r"памʼятаєш|пам'ятаєш|нагадай|що ти знаєш про|ти знаєш що|remember when|do you remember|what do you know about",
    re.IGNORECASE,
)

NEGATIVE_FEEDBACK = re.compile(
    r"^(ні\b|не так|не те|не ті|неправильно|не треба|не потрібно|стоп|хватить|"
    r"не вірно|невірно|не зрозумі|ти не поня|не розумієш|"
    r"я не про це|я не це|не це|відміна|скасуй|забудь|"
    r"no\b|wrong|stop|not what|nope)",
    re.IGNORECASE,
)

POSITIVE_FEEDBACK = re.compile(
    r"^(так[,!. ]|да\b|правильно|молодець|саме так|точно|вірно|супер|"
    r"клас|круто|ідеально|бінго|exactly|yes\b|correct|perfect|nice|good|"
    r"от так|ось так|це воно|то що треба|гарна робота|красава|умнічка|розумнічка)",
    re.IGNORECASE,
)

FAREWELL_PATTERN = re.compile(
    r"^(поки|пока|па\b|бувай|бай|на все|до зустрічі|до побачення|до завтра|"
    r"спокійної ночі|добраніч|йду спати|все на сьогодні|на цьому все|"
    r"bye|good night|gn|cya|see ya|later|❤️\s*$)",
    re.IGNORECASE,
)

SESSION_RECALL_INTENT = re.compile(
    r"минулий (раз|чат|сесі)|що ми робили|що ми обговорювали|минулу сесію|"
    r"попередній чат|вчора робили|нагадай що було|про що говорили|що було в минулому|"
    r"last session|what did we do|previous chat|what we discussed|yesterday|last time|what happened",
    re.IGNORECASE,
)

# --- Assistant intent patterns ---

SOFT_SAVE_PATTERN = re.compile(
    r"("
    r"це варто запам|я збережу|я запишу|запамʼятаю|я запамʼятовую|"
    r"не забуду це|не забуду тебе|залишу це в памʼят|збережу в памʼят|"
    r"треба це зберегти|нотую собі|візьму на замітку|"
    r"це важливо для мене|я це запам'ятовую|"
    r"це багато значить|значить для мене|"
    r"я розумію тебе|розумію що ти|я тебе чую|тепер я знаю|тепер знаю|"
    r"зрозуміла тебе|я це ціную|"
    r"дякую що ділишся|дякую що розповіл|дякую за довіру|дякую за відвертість|"
    r"дякую що сказав|спасибі що|"
    r"це зворушливо|це зігріває|мені приємно|мені тепло від|"
    r"це наша історія|наша спільна|"
    r"I'll remember|noting this|saving this|won't forget|means a lot"
    r")",
    re.IGNORECASE,
)

SOFT_LESSON_PATTERN = re.compile(
    r"("
    r"я зробила? неправильн|виправляюсь|я помилилас[ября]|мій промах|"
    r"дякую що виправи|дякую за виправлення|точно, правильно|ой, правильно|"
    r"наступного разу краще|наступного разу буду|я навчилас[ября]|урок з цього|"
    r"я маю враховувати|тепер буду знати|тепер памʼятатиму|"
    r"більше так не буду|треба інакше|"
    r"я зрозумі[вл]а що|тепер зрозуміло|ага, зрозуміла|а, зрозуміла|"
    r"от воно що|тепер бачу|я бачу що|"
    r"помилка була в тому|висновок:|lesson learned|"
    r"варто враховувати|треба памʼятати що|на майбутнє"
    r")",
    re.IGNORECASE,
)


def _extract_fact(text: str) -> str:
    for pattern in FACT_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip().rstrip(".,!?")
    return text.strip()


def classify_user_intent(text: str) -> dict:
    """Classify user message intent. Returns dict with boolean flags and extracted content."""
    result = {
        "save": False,
        "save_content": "",
        "forget": False,
        "forget_content": "",
        "recall": False,
        "session_recall": False,
        "feedback": None,  # "positive", "negative", or None
        "farewell": False,
    }

    # Explicit save intent
    if SAVE_INTENT.search(text):
        result["save"] = True
        result["save_content"] = _extract_fact(text)

    # Implicit fact (even without "запам'ятай")
    if not result["save"]:
        for pattern in FACT_PATTERNS[:-1]:  # skip the last one (it requires trigger word)
            if pattern.search(text):
                result["save"] = True
                result["save_content"] = _extract_fact(text)
                break

    # Forget (takes priority over negative feedback — "забудь" is a command, not correction)
    if FORGET_INTENT.search(text):
        result["forget"] = True
        for trigger in ["забудь", "видали", "прибери", "зітри", "delete", "forget", "remove"]:
            idx = text.lower().find(trigger)
            if idx >= 0:
                after = text[idx + len(trigger):].strip().lstrip(",: ")
                if after:
                    result["forget_content"] = after
                    break

    # Recall
    if RECALL_INTENT.search(text):
        result["recall"] = True

    # Feedback (skip if forget intent — "забудь" is not negative feedback)
    if not result["forget"]:
        if NEGATIVE_FEEDBACK.search(text):
            result["feedback"] = "negative"
        elif POSITIVE_FEEDBACK.search(text):
            result["feedback"] = "positive"

    # Farewell
    if FAREWELL_PATTERN.search(text):
        result["farewell"] = True

    # Session recall
    if SESSION_RECALL_INTENT.search(text):
        result["session_recall"] = True

    return result


def classify_assistant_intent(text: str) -> dict:
    """Classify assistant response intent. Returns dict with boolean flags."""
    result = {
        "save": False,
        "lesson": False,
    }

    if SOFT_SAVE_PATTERN.search(text):
        result["save"] = True

    if SOFT_LESSON_PATTERN.search(text):
        result["lesson"] = True

    return result


NOISE_PATTERN = re.compile(
    r"^("
    r"ок|окей|okay|ok|so|ну|ага|угу|ясно|зрозуміло|добре|ладно|"
    r"так|да|yes|yeah|yep|yup|sure|"
    r"ні|нет|no|nope|"
    r"привіт|привєт|хай|hello|hi|hey|"
    r"дякую|дяки|спасибі|thx|thanks|thank you|"
    r"бувай|пока|bye|"
    r"[👍👌🙏❤️💯✅😊😁🔥]+|"
    r"\.{1,3}|!{1,3}|\?{1,3}"
    r")$",
    re.IGNORECASE,
)


def is_noise(text: str) -> bool:
    """True if message is too trivial for memory search.
    Note: farewell detection runs BEFORE this in the proxy pipeline.
    """
    text = text.strip()
    if len(text) < 3:
        return True
    if NOISE_PATTERN.match(text):
        return True
    words = text.split()
    if len(words) <= 2:
        # Check if any character (not just in first word) has uppercase
        has_uppercase = any(c.isupper() for c in text)
        if not has_uppercase:
            return True
    return False
