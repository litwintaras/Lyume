# Code Review: Hybrid Search (Week 2)

**Дата:** 2026-03-26
**Коміт:** `efff78f`
**Рев'юер:** Claude Opus 4.6

---

## Загальна оцінка

Реалізація відповідає специфікації. RRF-формула коректна, міграція ідемпотентна, тести покривають основні сценарії. Нижче -- конкретні знахідки.

---

## Що зроблено добре

- **RRF-формула** (`rrf_merge`) реалізована точно за специфікацією: `1/(k + rank + 1)` -- правильне 1-indexed ранжування
- **Міграція** повністю ідемпотентна: `IF NOT EXISTS` для колонки, тригера, індексу; `CREATE OR REPLACE` для функції
- **`_to_tsquery_safe`** -- санітизація лапок і бекслешів, захист від SQL-injection через tsquery
- **`search_bm25_raw`** повертає ті самі поля що й `search_semantic`, що робить `rrf_merge` сумісним
- **Конфіг** -- `getattr` з дефолтами в `search_hybrid`, безпечно працює навіть без hybrid-полів у yaml

---

## Знахідки

### I1: BM25-результати не фільтруються по cooldown

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_manager.py`, рядок 348-353

План передбачав `_apply_cooldown_filter` для BM25-результатів при `explicit_recall=False`. В реалізації `search_hybrid` передає `explicit_recall` тільки в `search_semantic` (який має cooldown), але `search_bm25_raw` взагалі не фільтрує по `last_accessed`.

Наслідок: при автоматичному recall (explicit=False) BM25 може піднімати пам'яті, які vector search правильно відфільтрував по cooldown. Це порушує логіку cooldown.

**Рекомендація:** Додати `WHERE` clause з cooldown до `search_bm25_raw`, або фільтрувати після в `search_hybrid`.

### I2: Другий integration point не передає explicit_recall

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_proxy.py`, рядок 772

```python
mm.search_hybrid(user_input, limit=..., threshold=..., embedding=query_embedding)
```

Не передається `explicit_recall`. Дефолт в `search_hybrid` -- `explicit_recall=True`, що означає cooldown не працюватиме для Responses API path. Перший integration point (рядок 641) передає `explicit_recall=is_explicit` правильно.

**Рекомендація:** Додати `explicit_recall=False` (або визначити is_explicit для Responses API path).

### I3: _to_tsquery_safe недостатньо фільтрує спецсимволи

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_manager.py`, рядки 288-295

Функція видаляє тільки `'` і `\`. Але tsquery має більше спецсимволів: `!`, `&`, `|`, `(`, `)`, `:`, `*`. Якщо користувач напише запит типу `"error:500"` або `"test()"`, `to_tsquery('simple', ...)` кине syntax error.

**Рекомендація:** Фільтрувати всі non-alphanumeric символи, або використовувати `plainto_tsquery` замість `to_tsquery`:

```python
# Варіант 1: plainto_tsquery (автоматично AND-ить токени)
WHERE search_vector @@ plainto_tsquery('simple', $1)

# Варіант 2: regex-фільтр
import re
safe = [re.sub(r'[^\w]', '', t, flags=re.UNICODE) for t in tokens]
```

`plainto_tsquery` -- найпростіше і найбезпечніше рішення.

### I4: Embedding обчислюється двічі в search_hybrid

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_manager.py`, рядок 348

`search_hybrid` передає `embedding=query_embedding` в `search_semantic`, що добре. Але з proxy (рядок 641, 772) embedding вже обчислено -- і правильно передається. Все ОК, але в сигнатурі `search_hybrid` є `embedding: list[float] | None = None`, і якщо `None` -- `search_semantic` обчислить embedding знову всередині. Це не баг (proxy завжди передає), але варто задокументувати.

### S1: ts_rank обчислюється тричі в одному запиті

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_manager.py`, рядки 309-318

```sql
SELECT ..., ts_rank(search_vector, to_tsquery('simple', $1)) AS similarity
FROM memories_semantic
WHERE ... AND search_vector @@ to_tsquery('simple', $1)
ORDER BY ts_rank(search_vector, to_tsquery('simple', $1)) DESC
```

`to_tsquery` і `ts_rank` обчислюються 3 рази. PostgreSQL може оптимізувати це, але CTE або `ORDER BY similarity` було б чистіше:

```sql
ORDER BY similarity DESC
```

PostgreSQL дозволяє `ORDER BY` по alias.

### S2: Тест coverage -- немає тесту для спецсимволів в tsquery

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/tests/test_hybrid_search.py`

Тести покривають порожній запит, базовий BM25, RRF merge. Немає тесту для:
- Запит з `!`, `:`, `(`, `|` -- перевірити що `_to_tsquery_safe` не крашить DB
- Запит з кирилицею (проект -- українськомовний)
- `search_hybrid` з тільки BM25-результатами (vector повертає 0)
- `search_hybrid` з тільки vector-результатами (BM25 повертає 0)

### S3: Рядок 772 занадто довгий

**Файл:** `/home/tarik/.openclaw/workspace-lyume/python/memory_proxy.py`, рядок 772

Ternary + asyncio.gather в одному рядку ~200 символів. Читабельність страждає. Краще винести в змінну:

```python
search_coro = (
    mm.search_hybrid(user_input, ...)
    if getattr(cfg.memory, 'hybrid_search', False)
    else mm.search_semantic(user_input, ...)
)
memories, lessons = await asyncio.gather(search_coro, ...)
```

---

## Відповідність плану

| Таск | Статус | Коментар |
|------|--------|----------|
| 1. DB Migration | OK | Ідемпотентно, GIN-індекс є |
| 2. Config | OK | Три поля додані |
| 3. search_bm25_raw | OK | Працює, повертає правильну структуру |
| 4. rrf_merge | OK | Формула коректна |
| 5. search_hybrid | Deviation | Використовує `search_semantic` замість `search_semantic_raw` -- виправдане спрощення, бо search_semantic вже має cooldown |
| 6. Proxy integration | Issue | Другий integration point не передає `explicit_recall` (I2) |

**Відхилення від плану:**
- `search_semantic_raw` і `_apply_cooldown_filter` не створені -- замість них використовується існуючий `search_semantic`. Це розумне спрощення, але створює проблему I1: BM25-результати обходять cooldown.

---

## Підсумок по пріоритетах

| ID | Тип | Опис |
|----|-----|------|
| I1 | Improvement | BM25-результати ігнорують cooldown |
| I2 | Improvement | Другий proxy point не передає explicit_recall |
| I3 | Improvement | _to_tsquery_safe пропускає спецсимволи (!, :, (, ), *, \|) |
| I4 | Improvement | Документувати що embedding=None в search_hybrid подвоює обчислення |
| S1 | Suggestion | ORDER BY alias замість повторного ts_rank |
| S2 | Suggestion | Додати тести: спецсимволи, кирилиця, one-source-only |
| S3 | Suggestion | Розбити довгий рядок 772 для читабельності |

Критичних проблем не знайдено. I1+I2+I3 -- рекомендую виправити до merge.
