# Прогресс реализации MVP Exocortex 2

Документ отслеживает выполнение плана из `MVP_PLAN_2.md`.

## Общий статус

**Текущий этап:** после Этапа 1.  
**Следующий рекомендуемый фокус:** Этап 3 - ручное создание узлов и связей.

Новая базовая модель данных уже приведена к MVP 2-парадигме: старые типы узлов и ручных связей удалены из продуктовой модели, manual capture создает `quote` и `idea`, а semantic similarity больше не подтверждается как generic-связь.

Текущий автоматический тестовый набор: **90 тестов проходят**.

## Этап 1. Чистая модель данных ✅ (100%)

**Цель:** привести ядро данных к новой парадигме без legacy-совместимости.

- [x] Заменен набор типов узлов на MVP-набор:
  - `idea`;
  - `fact`;
  - `quote`;
  - `question`;
  - `conclusion`;
  - `source`.
- [x] Удалены legacy-типы узлов из продуктовой модели:
  - `excerpt`;
  - `thesis`;
  - `concept`;
  - `definition`.
- [x] Заменен набор ручных типов связей на MVP-набор:
  - `used_in`;
  - `derived_from`;
  - `contradicts`.
- [x] Удалены legacy-ручные связи из продуктовой модели и новой бизнес-логики:
  - `related_to`;
  - `supports`;
  - `example_of`;
  - `part_of`;
  - `similar_to`.
- [x] Semantic similarity оставлена как вычисляемый сигнал для hidden connection / suggestion flow, а не как ручная связь.
- [x] Добавлены явные поля модели и стандарты metadata:
  - `trust_status`;
  - `origin`;
  - `review_status`;
  - `user_comment`;
  - `title`;
  - `tags`.
- [x] Добавлены допустимые значения:
  - `trust_status`: `confirmed`, `suggested`, `auto_inferred`, `conflict`, `needs_clarification`;
  - `origin`: `user`, `llm`, `agent`, `system`;
  - `review_status`: `pending`, `accepted`, `rejected`, `edited`.
- [x] Обновлены LLM extraction schema/prompt под новые типы.
- [x] LLM-created nodes/edges помечаются как `suggested`, `origin=llm`, `review_status=pending`.
- [x] Обновлены manual capture и reader defaults:
  - выделенный фрагмент сохраняется как `quote`;
  - пользовательская мысль сохраняется как `idea`;
  - `source_text` сохраняет цитату/контекст происхождения мысли.
- [x] Обновлены API/CLI defaults для ручного добавления.
- [x] Обновлен graph UI: списки и стили типов узлов и связей соответствуют MVP 2.
- [x] Обновлен personalization feedback:
  - contradiction feedback может создавать `contradicts`;
  - hidden connection feedback больше не создает generic edge без выбранного типа;
  - вместо этого сохраняется pending metadata для дальнейшего review.
- [x] Обновлены тесты моделей, сериализации, LLM extraction, API/CLI, reader и proactive/personalization flows.
- [x] Добавлена/уточнена инструкция очистки старого storage: `python -m app.cli clear`.
- [x] Обновлены `README.md`, `SETUP.md`, `CHANGELOG.md`.

Критерий готовности:

- [x] Новая модель не содержит legacy alias.
- [x] Новые узлы и связи хранят доверие, происхождение, теги и заголовок.
- [x] Чистый storage создается и открывается.
- [x] Тесты проходят.

## Этап 2. Источники как полноценная часть графа ⏳ (частично, примерно 20%)

**Цель:** сделать provenance надежным и видимым для пользователя.

Уже есть:

- [x] Легкий provenance-режим через `source_text`, `source_url`, `document_title`, offsets и metadata.
- [x] `KnowledgeFragment` сохраняет исходный фрагмент или источник manual capture.
- [x] Боковая панель graph UI показывает `source_text` и metadata источника.
- [x] Reader передает `source_text`, URL/локальный источник, название документа и смещения выделения.

Еще не сделано:

- [ ] Нет полноценной модели source-узла или отдельной source-сущности.
- [ ] Нет API для создания/обновления источника как самостоятельной сущности.
- [ ] Reader пока не создает и не переиспользует `source`-узел.
- [ ] Узлы пока не связываются с source-узлом через `derived_from`.
- [ ] Нет тестов на создание source-узла и связь знания с источником.

## Этап 3. Ручное создание узлов и связей ⏳ (частично, примерно 15%)

**Цель:** сделать ручной граф главным пользовательским действием.

Уже есть:

- [x] Ручное сохранение выделения из `/reader` как `quote`.
- [x] Ручное сохранение мысли из `/reader` как `idea`.
- [x] API `/api/manual-fragments` принимает `node_type`.
- [x] В модели уже есть `title`, `tags`, `user_comment`, `trust_status`, `origin`, `review_status`.
- [x] Graph UI умеет просматривать и фильтровать существующие узлы/связи по текущим спискам типов.

Еще не сделано:

- [ ] Нет универсальных API:
  - `POST /api/nodes`;
  - `PATCH /api/nodes/{node_id}`;
  - `POST /api/edges`;
  - `PATCH /api/edges/{edge_id}`.
- [ ] В `/graph` нет создания узла.
- [ ] В `/graph` нет редактирования узла в боковой панели.
- [ ] В `/reader` пока нет выбора типа создаваемого узла для всех MVP-типов.
- [ ] В `/reader` пока нет ввода пользовательских тегов.
- [ ] Теги из reader пока не сохраняются как стандартное поле `tags`.
- [ ] Нет выбора двух узлов и создания связи в graph UI.
- [ ] Нет ручного выбора типа связи и комментария к связи.
- [ ] Нет тестов на полноценное ручное создание/редактирование узлов и связей.

## Этап 4. Предложения LLM при добавлении ⏳ (не начат, примерно 5%)

**Цель:** заменить автоматическое построение графа на подтверждаемые предложения.

Уже есть:

- [x] LLM extraction ограничен MVP 2-типами.
- [x] LLM-created nodes/edges помечаются как `suggested/pending`, а не как полностью подтвержденные пользовательские решения.

Еще не сделано:

- [ ] Нет модели `Suggestion`.
- [ ] Нет JSON-хранилища предложений.
- [ ] Нет API для генерации, списка, принятия и отклонения suggestions.
- [ ] `/api/knowledge` еще остается extraction endpoint и не переписан в полноценный suggestion flow.
- [ ] Нет accept/reject логики для LLM-предложений.
- [ ] Нет тестов suggestions lifecycle.

## Этап 5. Служебные связи и визуальное разделение слоев ⏳ (частично, примерно 10%)

**Цель:** отделить пользовательский смысл от машинных подсказок.

Уже есть:

- [x] Semantic similarity не сохраняется как ручная связь `similar_to`.
- [x] Hidden connection остается агентским инсайтом, а не подтвержденным edge.
- [x] У узлов и связей есть `trust_status`, `origin`, `review_status`.

Еще не сделано:

- [ ] Нет полноценного разделения edge layers: `manual`, `suggested`, `automatic`.
- [ ] API `/api/edges` не фильтрует связи по layer.
- [ ] Graph UI не показывает разные слои разными стилями.
- [ ] Нет фильтров graph UI по слою доверия.
- [ ] Нет тестов на фильтрацию и сериализацию слоев.

## Этап 6. Очередь предложений и новый inbox ⏳ (частично, примерно 20%)

**Цель:** превратить текущий inbox в review queue для развития графа.

Уже есть:

- [x] Inbox `/app` для агентских инсайтов.
- [x] API и CLI для inbox и feedback.
- [x] Реакции на contradiction, hidden connection и reminder.
- [x] История пользовательских реакций хранится в `.feedback.json`.
- [x] Hidden connection feedback больше не создает бессмысленную legacy-связь.

Еще не сделано:

- [ ] Inbox еще не переименован и не переосмыслен как полноценный Review/Suggestions flow.
- [ ] Нет объединения `Insight` и будущей модели `Suggestion`.
- [ ] Нет действий `edit and accept`, `defer`, `open in graph`.
- [ ] Contradiction flow еще не оформлен как полноценная review-сущность.
- [ ] Нет тестов нового review queue поверх suggestions.

## Этап 7. Внутренние рекомендации и мини-дайджест ⏳ (частично, примерно 35%)

**Цель:** сделать агент полезным без внешних рекомендаций.

Уже есть:

- [x] Proactive agent генерирует:
  - hidden connection;
  - contradiction;
  - reminder.
- [x] Дайджест ограничивается 1-3 инсайтами.
- [x] Дайджест сохраняется и доступен через API/CLI.
- [x] Есть web inbox для просмотра последних инсайтов.
- [x] Есть базовая personalization-логика на основе feedback.

Еще не сделано:

- [ ] Нет `possible duplicate`.
- [ ] Нет `open question follow-up`.
- [ ] Нет `source revisit`.
- [ ] Дайджест пока не ссылается на конкретные review items.
- [ ] Нет отдельного экрана "Сегодня".
- [ ] Нет метрик реакции на дайджест.

## Этап 8. Метрики MVP ⏳ (не начат, 0%)

**Цель:** измерить, становится ли граф полезнее от ручных действий пользователя.

- [ ] Нет event log.
- [ ] Не собираются события:
  - `node_created`;
  - `manual_edge_created`;
  - `source_opened`;
  - `suggestion_generated`;
  - `suggestion_accepted`;
  - `suggestion_rejected`;
  - `digest_opened`;
  - `review_item_reacted`;
  - `node_reopened`.
- [ ] Нет developer dashboard или CLI-команды `metrics`.
- [ ] Не считаются ключевые MVP-метрики.
- [ ] Нет тестов event log.

## Текущие ограничения и важные замечания

- Совместимость со старыми графами намеренно не поддерживается.
- Если в storage есть старые типы (`excerpt`, `thesis`, `concept`, `definition`, `related_to`, `supports`, `example_of`, `part_of`, `similar_to`), перед запуском новой версии нужно выполнить:

```bash
python -m app.cli clear
```

- `source_text` сейчас является контекстом происхождения знания, а не отдельным `source`-узлом.
- `tags` уже есть в модели, но UI reader пока не дает вводить их вручную.
- `/api/knowledge` все еще существует как extraction/import endpoint; по плану Этапа 4 его нужно удалить или переписать в источник предложений.

## Последняя проверка

- `venv\Scripts\python -m pytest -q`
- Результат: `90 passed`

## Последнее обновление

15 мая 2026
