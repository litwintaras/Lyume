# Lyume — Шпаргалка термінів

## Основні терміни

| Термін | Що це | Де в коді/конфізі |
|--------|-------|-------------------|
| **stale_days** | Скільки днів памʼять може не оновлюватись (`last_updated`) перш ніж архівується. Зараз: **365 днів** (~1 рік) | `config.yaml` → `consolidation.stale_days` / `memory_consolidator.py` Pass 3 |
| **stale_general_days** | Задуманий окремий поріг для категорії `general`. **[НЕ РЕАЛІЗОВАНО]** — є в конфізі (365), але код ігнорує категорію. Баг C2 | `config.yaml` → `consolidation.stale_general_days` |
| **cooldown_days** | "Період охолодження". Після використання памʼять не зʼявляється в авто-пошуку N днів. Зараз: **180 днів**. Явний запит ("нагадай мені...") обходить cooldown | `config.yaml` → `consolidation.cooldown_days` / `memory_manager.py` → `search_semantic()`, `search_lessons_balanced()` |
| **semantic_threshold** | Поріг косинусної подібності для кластеризації памʼятей. > 0.85 = кандидати на злиття | `config.yaml` → `consolidation.semantic_threshold` / `memory_consolidator.py` Pass 1 |
| **lesson_threshold** | Те саме для уроків (lessons) | `config.yaml` → `consolidation.lesson_threshold` / `memory_consolidator.py` Pass 2 |
| **archived** | Прапор: памʼять архівована (не в пошуку, не видалена). Відновлюється через explicit recall | БД: колонка `archived` в `memories_semantic`, `lessons` |
| **merged_into** | UUID памʼяті, в яку цей запис злили при консолідації. Трекає "куди поділась" стара памʼять | БД: колонка `merged_into` в `memories_semantic`, `lessons` |
| **explicit_recall** | Прапор пошуку. `True` = користувач явно просить → cooldown ігнорується. `False` = авто-recall → cooldown працює | `memory_proxy.py` → `memory_manager.py` |
| **last_updated** | Коли памʼять востаннє **ЗМІНЮВАЛАСЬ** (контент). Stale archive (Pass 3) дивиться саме на це | БД: колонка `last_updated` |
| **last_accessed** | Коли памʼять востаннє **ЧИТАЛАСЬ**. Стара `archive_stale()` використовувала це — неправильно за новою специфікацією | БД: колонка `last_accessed` |
| **trigger_count** | Скільки разів урок спрацював. При агрегації кластера — сумується. Більше = сильніший сигнал | БД: колонка `trigger_count` в `lessons` |
| **Union-Find** | Алгоритм кластеризації. Групує памʼяті за подібністю в "компоненти звʼязності" | `memory_consolidator.py` клас `UnionFind` |
| **Pass 1** | Semantic Merge — злиття подібних памʼятей. Union-Find кластеризація + LLM синтез через LM Studio | `memory_consolidator.py` → `find_semantic_clusters()` + `merge_semantic_cluster()` |
| **Pass 2** | Lesson Aggregation — злиття подібних уроків. Сумування `trigger_count`, деактивація дублів | `memory_consolidator.py` → `find_lesson_clusters()` + `aggregate_lesson_cluster()` |
| **Pass 3** | Stale Archive — архівування памʼятей не оновлених > `stale_days` днів | `memory_consolidator.py` → `archive_stale()` |

## Конфіг `consolidation:` (config.yaml)

| Поле | Значення | Що робить |
|------|----------|-----------|
| `enabled` | `true` | Ввімкнути/вимкнути консолідацію |
| `schedule` | `"03:00"` | Час запуску (systemd timer) |
| `semantic_threshold` | `0.85` | Поріг подібності для злиття памʼятей (Pass 1) |
| `lesson_threshold` | `0.85` | Поріг подібності для злиття уроків (Pass 2) |
| `cooldown_days` | `180` | Днів "тиші" після використання памʼяті |
| `stale_days` | `365` | Днів без оновлення → архів (Pass 3) |
| `stale_general_days` | `365` | **[НЕ РЕАЛІЗОВАНО]** Окремий поріг для категорії `general` |
| `log_file` | `"consolidation.log"` | Файл логів консолідації |
п
