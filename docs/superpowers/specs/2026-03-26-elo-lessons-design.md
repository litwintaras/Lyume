# ELO Rating System for Lessons — Специфікація

**Версія:** 1.0
**Дата:** 2026-03-26
**Статус:** затверджено

---

## 1. Проблема

Всі lessons мають однакову видимість незалежно від ефективності. Lesson, що спрацьовує часто але ніколи не допомагає, стоїть поруч з lesson, що реально змінює поведінку користувача. Немає механізму зворотного зв'язку.

---

## 2. Рішення

Реалізувати ELO рейтинг для кожного lesson (діапазон 0-100, стартові значення 50). Рейтинг впливає на видимість:
- Lessons з рейтингом < 20 не відображаються в результатах пошуку
- Lessons з рейтингом < 20 протягом N днів автоматично деактивуються

---

## 3. Фідбек — два канали

### 3.1 Implicit (LLM-оцінка)

Lyume після кожної відповіді оцінює, використала вона injected lessons чи ні.

**Маркери:**
- `>>USEFUL:<lesson_id>` — lesson був використаний і допоміг
- `>>USELESS:<lesson_id>` — lesson був доступний, але не використаний

**Вплив:**
- `>>USEFUL` → ELO: +5 (default)
- `>>USELESS` → ELO: 0 (не карає — "не підходило зараз" ≠ "поганий lesson")

### 3.2 Explicit (override користувача)

Користувач явно оцінює quality lesson через маркер.

**Маркери:**
- `>>RATE_LESSON:<lesson_id>:+` — позитивна оцінка
- `>>RATE_LESSON:<lesson_id>:-` — негативна оцінка

**Вплив:**
- `+` → ELO: +10 (default)
- `-` → ELO: -10 (default)

### 3.3 Правила обробки

1. **Clamp:** рейтинг завжди в діапазоні [0, 100]
2. **Пріоритет:** якщо для одного lesson_id в одній відповіді є обидва (implicit + explicit), застосовується тільки explicit
3. **Дедублікація:** один lesson_id оцінюється максимум один раз за одну відповідь (перший запис виграє або явно вказано як первинний)

---

## 4. Змінення бази даних

### 4.1 Таблиця `lessons`

Додати два нові стовпці:

| Стовпець | Тип | Default | Опис |
|----------|-----|---------|------|
| `elo_rating` | INTEGER | 50 | Поточний ELO рейтинг [0, 100] |
| `elo_below_since` | TIMESTAMPTZ | NULL | Timestamp, коли рейтинг впав нижче порогу; NULL якщо рейтинг >= порогу |

### 4.2 Міграція

```sql
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_rating INTEGER DEFAULT 50;
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS elo_below_since TIMESTAMPTZ DEFAULT NULL;
```

Міграція ідемпотентна (не падає, якщо стовпці вже існують).

---

## 5. Пошук lessons

### 5.1 Функції `search_lessons()` і `search_lessons_balanced()`

**Зміна:** додати умову в WHERE clause:
```sql
AND elo_rating >= :elo_floor
```

**Параметр:** `:elo_floor` = `cfg.lessons.elo_floor` (default 20)

**Що не змінюється:** cosine similarity ранжування залишається основою. ELO фільтр — це binary gate, не score.

---

## 6. Деактивація lessons

### 6.1 Process: Consolidation Pass

В `memory_consolidator.py` додати новий pass до ночі:

**Умова:** знайти всі lessons де:
```sql
elo_below_since IS NOT NULL
AND elo_below_since < NOW() - INTERVAL 'N days'
```

**Дія:** `UPDATE lessons SET active = false WHERE ...`

**N:** `cfg.lessons.elo_deactivate_days` (default 30)

**Логування:** записати в debug: які lessons деактивовані, їх ID і рейтинги.

---

## 7. Обробка маркерів

### 7.1 Місце обробки

File: `python/memory_proxy.py`
Функція: `process_markers()` або аналогічна

### 7.2 Маркери й дії

| Маркер | Приклад | Дія | ELO delta |
|--------|---------|-----|-----------|
| USEFUL | `>>USEFUL:lesson_abc` | LLM використала | +5 |
| USELESS | `>>USELESS:lesson_abc` | LLM мала доступ, не використала | 0 |
| RATE_LESSON + | `>>RATE_LESSON:lesson_abc:+` | Користувач схвалив | +10 |
| RATE_LESSON - | `>>RATE_LESSON:lesson_abc:-` | Користувач схвалив негативно | -10 |

### 7.3 Алгоритм обробки

```
1. Парсити всі маркери з відповіді
2. Групувати по lesson_id
3. Для кожної групи:
   - Якщо є EXPLICIT (RATE_LESSON) → застосувати це
   - Інакше застосувати IMPLICIT (USEFUL/USELESS)
4. Для кожного lesson_id:
   - Викликати mm.update_lesson_elo(lesson_id, delta)
```

---

## 8. Новий метод MemoryManager

**File:** `python/memory_manager.py`

```python
async def update_lesson_elo(
    self,
    lesson_id: str,
    delta: int
) -> int:
    """
    Оновити ELO рейтинг lesson.

    Аргументи:
        lesson_id (str): ID lesson
        delta (int): зміна рейтингу (позитивне/негативне)

    Повертає:
        int: новий рейтинг [0, 100]

    Побічні ефекти:
        - Оновлює elo_rating: CLAMP(elo_rating + delta, 0, 100)
        - Якщо новий рейтинг < elo_floor і elo_below_since IS NULL:
            SET elo_below_since = NOW()
        - Якщо новий рейтинг >= elo_floor:
            SET elo_below_since = NULL
    """
```

**Логіка:**

1. Прочитати поточний `elo_rating`
2. Обчислити: `new_rating = max(0, min(100, elo_rating + delta))`
3. UPDATE:
   ```sql
   UPDATE lessons
   SET elo_rating = :new_rating,
       elo_below_since = CASE
           WHEN :new_rating < :elo_floor AND elo_below_since IS NULL
               THEN NOW()
           WHEN :new_rating >= :elo_floor
               THEN NULL
           ELSE elo_below_since
       END
   WHERE id = :lesson_id
   RETURNING elo_rating
   ```
4. Повернути новий рейтинг

---

## 9. Конфіг

**File:** `python/config.yaml`

```yaml
lessons:
  elo_start: 50              # стартовий рейтинг для нових lessons
  elo_implicit_delta: 5      # зміна при USEFUL/USELESS
  elo_explicit_delta: 10     # зміна при RATE_LESSON
  elo_floor: 20              # поріг видимості
  elo_deactivate_days: 30    # днів нижче порогу до деактивації
```

---

## 10. System Prompt зміни

**Документ:** SOUL.md або система prompt injection для Lyume

**Додати інструкції:**

1. **Після кожної відповіді**, якщо в контексті були injected lessons (з `<intuition>` блоку):
   - Для кожного lesson, що був використаний → `>>USEFUL:<lesson_id>`
   - Для кожного lesson, що був доступний але не використаний → `>>USELESS:<lesson_id>`

2. **Пояснити користувачу** (один раз на сесію або в help):
   > Ви можете явно оцінити quality lesson маркером `>>RATE_LESSON:<id>:+` (схвалити) або `>>RATE_LESSON:<id>:-` (не схвалити).

---

## 11. Файли, що змінюються

| Файл | Зміни |
|------|-------|
| `python/memory_manager.py` | Метод `update_lesson_elo()`, фільтр `AND elo_rating >= :elo_floor` в `search_lessons()`, `search_lessons_balanced()` |
| `python/memory_proxy.py` | Парсинг маркерів USEFUL, USELESS, RATE_LESSON в `process_markers()` |
| `python/memory_consolidator.py` | Новий pass для деактивації lessons |
| `python/config.yaml` | Нова секція `lessons` з ELO параметрами |
| Database migration | ALTER TABLE lessons (2 стовпці) |
| SOUL.md або system prompt | Інструкції для Lyume про implicit оцінювання |

---

## 12. Тестування

### 12.1 Unit тести

- `test_update_lesson_elo`: clamping, elo_below_since логіка
- `test_search_lessons_elo_filter`: lessons < floor не повертаються
- `test_marker_parsing`: USEFUL, USELESS, RATE_LESSON парсинг
- `test_explicit_override`: explicit побивають implicit в одній відповіді

### 12.2 Integration тести

- Повна flow: LLM оцінює → markers → update → пошук
- Деактивація: створити low-rated lesson → wait 30+ днів → check active=false

---

## 13. Порядок впровадження

1. Database migration
2. Оновити `memory_manager.py`: метод + фільтри в search
3. Оновити `config.yaml`
4. Оновити `memory_proxy.py`: парсинг маркерів
5. Оновити `memory_consolidator.py`: deactivation pass
6. Оновити SOUL.md / system prompt
7. Unit тести
8. Integration тести
9. Deployment & monitoring

---

## 14. Моніторинг

**Метрики для логування:**

- Кількість lessons в кожному діапазоні рейтингу: [0-20], [20-50], [50-100]
- Кількість lessons в статусі `elo_below_since IS NOT NULL`
- Кількість lessons деактивованих за ніч (consolidation pass)
- Кількість markers оброблено за день (USEFUL/USELESS/RATE_LESSON)

**Алерти:**

- Якщо > 30% lessons < 20 → можлива проблема з якістю
