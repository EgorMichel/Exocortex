# Refactoring Plan

План описывает архитектурные исправления, которые стоит заложить на этапе MVP, чтобы Exocortex мог дойти до полной MVP-версии без лишних переделок и затем масштабироваться к продукту из `EXOCORTEX_2.md`.

## Кратко о найденных проблемах

1. **Однопользовательская архитектура.**
   Сейчас API держит глобальные singleton-сервисы и один общий `GraphRepository`. Для локального MVP это допустимо, но для облачного сервиса без `user_id` и `graph_id` позже придется переписывать модели, storage, API и агента.

2. **Источник смешан со смысловым графом.**
   Концепт требует хранить источник как provenance-контекст у узлов. При этом LLM extraction все еще допускает `source` как автоматически извлекаемый `NodeType`, что может загрязнять смысловой слой графа.

3. **Типы связей не соответствуют MVP-концепту.**
   В описании MVP есть `связано с`, `подтверждает`, `противоречит`, `следует из`, `является примером`, `уточняет`. В коде остались только `used_in`, `derived_from`, `contradicts`, из-за чего агентские hidden connections нельзя нормально подтверждать как ручные связи.

4. **Ручные, служебные и предложенные связи недостаточно разделены.**
   В модели есть `trust_status`, `origin`, `review_status`, но нет явного слоя связи: manual/service/suggested. Это повышает риск смешать пользовательский смысл с машинными подсказками.

5. **Repository не защищает целостность графа.**
   `GraphRepository.add_edge()` может добавить ребро между несуществующими узлами, а NetworkX создаст пустые узлы. Часть инвариантов сейчас держится только в API.

6. **Storage не готов к росту и параллельности.**
   GEXF/JSON используются как основное хранилище, сохранение перезаписывает файлы целиком, нет schema version, atomic write и lock. Это риск для scheduler, API-запросов и миграций.

7. **Слишком крупные модули.**
   `app/api/routes.py`, `app/agents/proactive.py` и `app/web/graph.html` уже стали центрами накопления сложности. Новые фичи будут усиливать связанность.

8. **LLM-ошибки скрываются как пустой результат.**
   Ошибка extraction сейчас может выглядеть как успешная операция с нулем созданных узлов. Для MVP это ухудшает наблюдаемость и доверие.

9. **Внешний URL ingest небезопасен для будущего web-сервиса.**
   `/api/sources` принимает произвольный URL и делает синхронный `urlopen()` внутри async endpoint. Нужны ограничения, таймауты, лимиты размера и защита от SSRF.

## Цели рефакторинга

- Сохранить скорость разработки MVP.
- Зафиксировать доменные границы: пользовательский смысл отдельно от машинных подсказок.
- Подготовить систему к `user_id`/`graph_id`, даже если MVP пока локальный.
- Упростить будущую замену NetworkX/GEXF на SQLite, Postgres, Neo4j или гибридное хранилище.
- Снизить риск потери данных и битого графа.
- Сделать агента producer'ом предложений, а не неявным автором смыслового графа.

## План работ

### Фаза 1. Доменная модель и инварианты

1. Обновить `NodeType`.
   - Оставить knowledge-типы: `idea`, `fact`, `quote`, `question`, `conclusion`.
   - `source` разрешать только как явный ручной объект анализа или вынести в отдельную модель.
   - Запретить автоматическое создание `source`-узлов из LLM/capture.

2. Обновить `EdgeType` под MVP.
   - Добавить: `related_to`, `supports`, `contradicts`, `derived_from`, `example_of`, `clarifies`.
   - Решить судьбу `used_in`: либо мигрировать в `related_to`, либо оставить как legacy/internal только через миграцию.

3. Ввести явный слой связи.
   - Например: `EdgeLayer.MANUAL`, `EdgeLayer.SERVICE`, `EdgeLayer.SUGGESTED`.
   - Ручные связи должны появляться только из пользовательского действия.
   - Служебные связи должны быть вычисляемыми или явно помеченными как service.

4. Усилить `GraphRepository`.
   - `add_edge()` должен отклонять ребра с несуществующими узлами.
   - `get_neighbors()` и `get_related_nodes()` должны уметь работать с входящими и исходящими ребрами.
   - Добавить тесты на битые edge, directed/undirected navigation и layer filtering.

### Фаза 2. Предложения агента вместо прямого изменения смысла

1. Ввести модель `Suggestion` / `AgentProposal`.
   - Типы: proposed edge, proposed tag, possible duplicate, possible contradiction, reminder.
   - Поля: `id`, `proposal_type`, `node_ids`, `edge_ids`, `payload`, `score`, `origin`, `review_status`, `created_at`.

2. Перевести hidden connections в proposals.
   - Агент не создает manual edge.
   - Подтверждение пользователя превращает proposal в `ManualEdge`.

3. Уточнить feedback-flow.
   - `confirm` для hidden connection должен создавать edge выбранного типа.
   - `reject` должен закрывать proposal без изменения смыслового графа.
   - `refine` должен сохранять пользовательскую правку как новую manual-связь или обновленное предложение.

4. Сделать contradiction-flow явным.
   - LLM может создать `possible_contradiction`.
   - Только пользовательское подтверждение создает `contradicts` manual edge или меняет trust status узлов.

### Фаза 3. Storage и миграции

1. Ввести интерфейс storage adapter.
   - Например `GraphStore` / `GraphRepositoryProtocol`.
   - Текущая реализация может остаться `NetworkXFileGraphStore`.
   - API, CLI и агенты должны зависеть от интерфейса, а не от деталей GEXF.

2. Перестать считать GEXF главным форматом хранения.
   - Сделать canonical storage: versioned JSON или SQLite.
   - GEXF оставить как export/import формат.

3. Добавить schema version.
   - Хранить версию схемы в storage.
   - Добавить первый migration path для старых `used_in`/`source` случаев.

4. Сделать сохранение безопаснее.
   - Atomic write через временный файл и rename.
   - File lock для CLI/API/scheduler.
   - Тест на частичный write и повторную загрузку.

5. Подготовить `user_id` и `graph_id`.
   - Добавить дефолтные значения `local` и `default`.
   - Протащить их через storage paths, models и API dependencies.
   - Не обязательно делать auth в MVP, но границу данных лучше заложить сейчас.

### Фаза 4. API и dependency boundaries

1. Разбить `app/api/routes.py`.
   - `schemas.py`
   - `node_routes.py`
   - `edge_routes.py`
   - `source_routes.py`
   - `agent_routes.py`
   - `app_factory.py`

2. Заменить module-level globals на FastAPI dependencies.
   - `get_settings()`
   - `get_graph_context()`
   - `get_graph_store()`
   - `get_llm_service()`
   - `get_agent_service()`

3. Сделать ответы ingestion более честными.
   - Возвращать `llm_status`: `skipped`, `succeeded`, `failed`.
   - Возвращать `warnings` и `errors`.
   - Не маскировать LLM failure под обычный пустой результат.

4. Ограничить external source ingest.
   - Перенести blocking I/O из async endpoint в threadpool или заменить на async HTTP client.
   - Добавить URL scheme allowlist.
   - Запретить localhost/private IP по умолчанию.
   - Добавить max response size и content-type проверки.

### Фаза 5. Агентский backend

1. Разбить `app/agents/proactive.py`.
   - `candidate_pairs.py`
   - `similarity.py`
   - `contradictions.py`
   - `reminders.py`
   - `digest.py`
   - `state_store.py`

2. Разделить анализ и запись.
   - Analyzer возвращает proposals/insights.
   - Application service решает, что сохранять.

3. Сделать служебные связи отдельным слоем.
   - Общий источник, общий тег, semantic similarity и duplicate должны быть service/computed, а не manual.
   - UI должен показывать их другим стилем.

4. Добавить наблюдаемость.
   - Structured logging.
   - Счетчики: analyzed nodes, candidate pairs, LLM calls, proposals created, failures.

### Фаза 6. Frontend-разделение

1. Разбить `app/web/graph.html`.
   - На MVP можно оставить single-file delivery, но внутри выделить модули или хотя бы логические секции:
     - API client
     - graph state
     - layout/render
     - inspector
     - node editor
     - edge editor

2. Отразить новые слои графа в UI.
   - Manual edges: основной визуальный слой.
   - Service links: приглушенный/пунктирный слой.
   - Suggestions: отдельные cards/actions, не полноценные связи до подтверждения.

3. Добавить выбор типа связи при подтверждении hidden connection.

## Рекомендуемый порядок выполнения

1. Исправить `source`-узлы и `EdgeType`.
2. Добавить `edge_layer` и repository-инварианты.
3. Ввести `Suggestion`/`AgentProposal`.
4. Перевести hidden connections и contradictions на proposal-flow.
5. Добавить `user_id`/`graph_id` с дефолтами.
6. Ввести storage adapter и schema version.
7. Разбить API routes.
8. Улучшить LLM error reporting.
9. Защитить external source ingest.
10. Разбить agent/frontend крупные файлы.

## Definition of Done

- Тесты покрывают запрет битых edge и автоматических `source`-узлов.
- Ручные, служебные и предложенные связи различимы в данных и UI.
- Агент не записывает пользовательский смысл без подтверждения.
- API и CLI работают через общий storage/repository interface.
- Storage имеет schema version и безопасное сохранение.
- В моделях и storage есть дефолтные `user_id`/`graph_id`.
- `pytest`, `compileall` и базовая type-check команда проходят или имеют зафиксированные исключения.

