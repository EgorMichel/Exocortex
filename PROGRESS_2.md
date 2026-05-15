# Прогресс реализации MVP Exocortex 2

Документ отслеживает выполнение плана из `MVP_PLAN_2.md`.

## Общий статус

**Текущий этап:** после Этапа 2.  
**Следующий рекомендуемый фокус:** Этап 4 - предложения LLM при добавлении.

Новая базовая модель данных уже приведена к MVP 2-парадигме: старые типы узлов и ручных связей удалены из продуктовой модели, manual capture создает `quote` и `idea`, semantic similarity больше не подтверждается как generic-связь, а ручные узлы и связи стали основным пользовательским действием через API, `/reader` и `/graph`.

Текущий автоматический тестовый набор: **97 тестов проходят**.

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

## Этап 2. Источники как provenance-привязки ✅ (100%)

**Цель:** сделать provenance надежным и видимым для пользователя.

Уточнение продукта: источник не должен автоматически становиться смысловым узлом графа. Для обычного reader/capture source хранится как структурированная provenance-привязка у knowledge-узла: URL/локальный путь, название документа, автор, позиция, выделенный фрагмент, offsets и комментарий. `derived_from` остается ручной смысловой связью между knowledge-узлами, например для вывода из фактов или следствия из утверждений, и не используется для технической привязки к источнику.

- [x] Стандартизирована provenance-привязка у узла:
  - `source_id`;
  - `source_url`;
  - `document_title`;
  - `author`;
  - `published_at`;
  - `added_at`;
  - `source_type`;
  - `position`;
  - `offset_start`;
  - `offset_end`;
  - `source_text`;
  - `user_comment`.
- [x] Сохранена совместимость с текущими `source_text`, metadata и `KnowledgeFragment`.
- [x] Добавлен API `PATCH /api/nodes/{node_id}/provenance` для создания/обновления provenance-привязки у узла.
- [x] Node responses стабильно возвращают `provenance`, `source_id`, `source_url`, `document_title` вместе с существующими metadata и `source_text`.
- [x] `POST /api/sources` не сломан и продолжает импортировать внешний текст через существующий путь.
- [x] `/reader` при сохранении выделения/мысли сохраняет структурированный provenance.
- [x] Для одного файла/URL переиспользуется общий `source_id`.
- [x] `/reader` и manual capture не создают `source`-узлы.
- [x] `/reader` и manual capture не создают `derived_from` edge к источнику.
- [x] В боковой панели `/graph` явно показываются title, URL/local path, `source_text`, offsets и metadata источника.
- [x] Добавлена ссылка открытия `source_url`, если она есть.
- [x] Добавлена подсветка узлов с тем же `source_id`.
- [x] Добавлены API/reader regression tests на создание, обновление, переиспользование и ограничения source attachment.

Критерий готовности:

- [x] Пользователь может открыть узел и понять, откуда он появился.
- [x] Цитата или мысль из reader содержит структурированную provenance-привязку и удобный переход к исходному источнику.

## Этап 3. Ручное создание узлов и связей ✅ (100%)

**Цель:** сделать ручной граф главным пользовательским действием.

- [x] Ручное сохранение выделения из `/reader` как `quote`.
- [x] Ручное сохранение мысли из `/reader` как `idea`.
- [x] API `/api/manual-fragments` принимает `node_type`.
- [x] В модели уже есть `title`, `tags`, `user_comment`, `trust_status`, `origin`, `review_status`.
- [x] Graph UI умеет просматривать и фильтровать существующие узлы/связи по текущим спискам типов.
- [x] Добавлены универсальные API:
  - `POST /api/nodes`;
  - `PATCH /api/nodes/{node_id}`;
  - `POST /api/edges`;
  - `PATCH /api/edges/{edge_id}`.
- [x] Новые ручные узлы получают `origin=user`, `trust_status=confirmed`, `review_status=accepted`.
- [x] Новые ручные связи получают `origin=user`, `trust_status=confirmed`, `review_status=accepted`.
- [x] В `/graph` добавлено создание узла.
- [x] В `/graph` добавлено редактирование выбранного узла в боковой панели.
- [x] В `/graph` добавлен выбор двух узлов как source/target и создание ручной связи.
- [x] В `/graph` добавлен выбор типа связи и пользовательский комментарий к связи.
- [x] В `/reader` добавлен выбор типа создаваемого узла для всех MVP-типов:
  - `idea`;
  - `fact`;
  - `quote`;
  - `question`;
  - `conclusion`;
  - `source`.
- [x] В `/reader` сохранены defaults:
  - выделенный фрагмент без редактирования по умолчанию сохраняется как `quote`;
  - пользовательская мысль по умолчанию сохраняется как `idea`;
  - пользователь может явно изменить тип перед сохранением.
- [x] В `/reader` добавлен ввод пользовательских тегов.
- [x] Теги из `/reader` сохраняются в стандартное поле `tags`.
- [x] Добавлены API-тесты создания и редактирования узлов.
- [x] Добавлены API-тесты создания и редактирования связей.
- [x] Добавлены тесты reader defaults и tags.
- [x] Добавлены тесты, что legacy-типы не принимаются.
- [x] Добавлены тесты, что ручные узлы/связи получают `origin=user`, `trust_status=confirmed`, `review_status=accepted`.

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

- `source_text` сейчас является контекстом происхождения знания; source хранится как provenance-привязка, а не как автоматически создаваемый смысловой `source`-узел.
- `tags` уже есть в модели; `/reader` и `/graph` позволяют вводить пользовательские теги вручную.
- `/api/knowledge` все еще существует как extraction/import endpoint; по плану Этапа 4 его нужно удалить или переписать в источник предложений.

## Последняя проверка

- `venv\Scripts\python -m pytest -q`
- Результат: `97 passed`

## Последнее обновление

15 мая 2026
