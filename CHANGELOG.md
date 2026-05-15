# Changelog

Все заметные изменения в проекте Exocortex будут задокументированы в этом файле.

## [Unreleased]

### Добавлено
- **MVP 2 Этап 2: источники как provenance-привязки**:
  - Структурированная provenance-привязка у узла: `source_id`, `source_url`, `document_title`, `author`, `published_at`, `added_at`, `source_type`, `position`, `offset_start`, `offset_end`, `source_text`, `user_comment`
  - API `PATCH /api/nodes/{node_id}/provenance` для создания и обновления provenance без создания source-узла
  - Ответы узлов возвращают `provenance` и стабильные поля `source_id`, `source_url`, `document_title`
  - `/reader` и manual capture переиспользуют общий `source_id` для одного URL/локального файла
  - `/reader` и manual capture не создают `source`-узлы и не создают `derived_from`-связь к источнику
  - `/graph` показывает source title/URL, `source_text`, offsets и metadata источника в боковой панели
  - `/graph` получил ссылку открытия `source_url` и подсветку узлов с тем же `source_id`
- **MVP 2 Этап 3: ручное создание узлов и связей**:
  - Пользовательские endpoints `POST /api/nodes`, `PATCH /api/nodes/{node_id}`, `POST /api/edges`, `PATCH /api/edges/{edge_id}`
  - Создание ручных узлов и связей в `/graph`
  - Редактирование выбранного узла в боковой панели `/graph`
  - Выбор двух узлов source/target и создание ручной связи `used_in`, `derived_from` или `contradicts`
  - Выбор MVP 2-типа и ввод тегов в `/reader`; теги сохраняются в стандартное поле `tags`
  - Ручные узлы и связи при создании получают `origin=user`, `trust_status=confirmed`, `review_status=accepted`
- **Запуск приложения**:
  - Точка входа `python -m app.main` для FastAPI-сервера
  - CLI `python -m app.cli` с командами `add`, `stats`, `list`, `search`, `forgotten`, `clear`
  - Dockerfile и `docker-compose.yml`
- **Конфигурация**:
  - Загрузка `config/.env`
  - Поддержка `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_API_BASE`, `OLLAMA_BASE_URL`, `STORAGE_PATH`
  - Локальный LLM-провайдер Ollama через OpenAI-compatible API
  - Автоматическое создание директории хранения графа
- **Базовая структура проекта**: Модульная архитектура с разделением на `core`, `agents`, `llm`, `api`, `services`, `utils`
- **Модели данных** (`app/core/models.py`):
  - `Node`: Узел графа знаний с полями id, тип, содержание, редактируемый `source_text`, метаданные, `trust_status`, `origin`, `review_status`, `user_comment`, `title`, `tags`, параметры памяти (strength, decay_rate, last_interacted)
  - `Edge`: Ручная логическая связь между узлами с полями id, тип, слой, источник, цель, вес, метаданные, `trust_status`, `origin`, `review_status`, `user_comment`
  - `NodeType`: MVP 2-типы узлов (IDEA, FACT, QUOTE, QUESTION, CONCLUSION, SOURCE)
  - `EdgeType`: MVP-типы ручных связей (`USED_IN`, `DERIVED_FROM`, `CONTRADICTS`)
  - `TrustStatus`, `Origin`, `ReviewStatus`: стандартизированные статусы доверия, происхождения и проверки
  - `KnowledgeFragment`: Исходный фрагмент знания с метаданными и `llm_status`/`warnings`/`errors`
  - `AgentProposal`: Reviewable предложения агента (`proposed_edge`, `proposed_tag`, `possible_duplicate`, `possible_contradiction`, `reminder`)
- **Графовый репозиторий** (`app/core/repository.py`):
  - CRUD операции для узлов и связей
  - Поиск и фильтрация узлов по типу, содержимому
  - Получение «забытых» узлов на основе параметров памяти
  - Навигация по графу (соседние узлы, связанные узлы)
  - Canonical versioned JSON storage (`.graph.json`) со schema version, atomic write и file lock; GEXF оставлен как export/fallback
  - Сохранение/загрузка фрагментов знаний и proposals в JSON
  - Статистика графа
- **Интеграция LLM** (`app/llm/extraction.py`):
  - Пайплайн извлечения сущностей и связей из текста
  - Извлечение выполняется только через настроенный LLM-клиент
  - Поддержка только MVP 2-типов узлов и ручных связей
- **API слой** (`app/api/routes.py`):
  - REST эндпоинты для управления графом знаний
  - Эндпоинты чтения: GET /api/nodes, GET /api/edges, POST /api/knowledge, GET /api/stats, GET /api/fragments
  - Ручные CRUD endpoints: POST /api/nodes, PATCH /api/nodes/{node_id}, POST /api/edges, PATCH /api/edges/{edge_id}
- **Агент** (`app/agents/`):
  - Заготовка для проактивного агента
  - Модели `Insight`, `InsightType`, `Digest` и JSON-хранилище дайджестов
  - `ProactiveAgent` для фонового анализа графа
  - Сохранение agent observations как proposals отдельно от ручного смыслового графа
  - Поиск забываемого контента на основе `strength`, `decay_rate`, `last_interacted`
  - Поиск неочевидных связей между похожими узлами без существующего ребра
  - Локальные векторные эмбеддинги для семантического сравнения узлов
  - LLM-проверка кандидатов на противоречия через `detect_contradiction` или OpenAI-compatible client
  - Батчевая OpenAI-compatible проверка противоречий: несколько похожих пар в одном prompt с JSON-массивом результатов
  - Инкрементальное состояние анализа `.analysis_state.json` для пропуска пар, где оба узла и параметры анализа не изменились
  - Сохранение сравниваемых утверждений (`statement_a`, `statement_b`) в metadata инсайтов-противоречий
  - Приоритизация и форматирование дайджеста на 1-3 инсайта
  - APScheduler-интеграция для периодического запуска агента
  - CLI-команды `analyze` и `digest`
  - API endpoints `POST /api/agent/analyze`, `GET /api/digest`, `GET /api/insights`, `POST /api/sources`
- **Внешние источники** (`app/services/external_sources.py`):
  - Импорт прямого текста, UTF-8 файлов и текстовых URL в граф знаний через существующий LLM-пайплайн
  - URL ingest: allowlist `http/https`, запрет localhost/private IP по умолчанию, проверка content-type, лимит размера и перенос blocking I/O в thread
- **Ручной захват фрагментов** (`app/services/manual_capture.py`):
  - Тип узла `quote` для текста, вручную выделенного пользователем
  - Поле `source_text` у узла для хранения редактируемой цитаты/абзаца, на котором основана пользовательская мысль
  - Сохранение ручной мысли как `idea`: `content` хранит мысль, `source_text` хранит источник, `KnowledgeFragment.content` сохраняет источник как provenance
  - Сохранение выделенного текста в граф без LLM-обработки и без автоматического извлечения связей
  - API endpoint `POST /api/manual-fragments` принимает `source_text` и `node_type`
  - API endpoint `POST /api/manual-fragments` сохраняет пользовательские теги в стандартное поле `tags`
  - CLI-команда `add-manual` получила опцию `--source-text`
  - Встроенная web-читалка `/reader` для локальных UTF-8 текстовых и Markdown-файлов
  - `/reader` позволяет выбрать MVP 2-тип узла для выделения или мысли и добавить пользовательские теги
  - Контекстное меню читалки: выделить текст, нажать правой кнопкой мыши, выбрать `Add to Graph`
  - Правая панель читалки для записи мысли, редактирования источника, скрытия источника и сохранения через `Add Thought`
  - Контекстное меню читалки получило действие `Add as Source`, которое переносит выделенный абзац в поле источника
- **Персонализация** (`app/services/personalization.py`):
  - Inbox сохранённых инсайтов с учётом последней реакции пользователя
  - JSON-хранилище пользовательских реакций `.feedback.json`
  - Реакции на противоречия, скрытые связи и напоминания
  - Обновление графа на основе feedback: усиление узлов, пометки разрешений, создание подтверждённых противоречий
  - Hidden connection `confirm/refine` создаёт ручную `used_in`-связь по умолчанию; API feedback может передать выбранный `edge_type`; `reject` закрывает предложение без изменения смыслового графа
  - Базовая модель интересов: счётчики действий, частоты тем, взаимодействия с узлами, стиль сообщений
  - Встроенный web UI `/app` для inbox, реакций, запуска анализа и просмотра профиля интересов
  - Адаптация приоритизации инсайтов агента по темам, истории реакций и `interest_score` узлов
  - CLI-команды `inbox`, `react`, `interests`
  - API endpoints `GET /api/inbox`, `POST /api/insights/{insight_id}/feedback`, `GET /api/personalization`
- **Конфигурация** (`config/`):
  - Базовые конфигурационные файлы
  - Настройки агента: `AGENT_ENABLED`, `AGENT_INTERVAL_MINUTES`, `AGENT_DIGEST_LIMIT`, `AGENT_FORGOTTEN_THRESHOLD`, `AGENT_CONTRADICTION_BATCH_SIZE`
- **Тесты** (`tests/`):
  - Тесты для моделей данных, репозитория, LLM-извлечения, API-конфигурации, CLI, ручного добавления фрагментов, проактивного агента, web UI и персонализации
  - Покрытие тестами основных операций CRUD
  - Тесты сохранения/загрузки графа
  - Тесты генерации напоминаний, скрытых связей, противоречий, векторного поиска, импорта источников и сохранения дайджестов
  - Тесты оптимизированного анализа: переиспользование candidate pairs, ранний skip без LLM-клиента, батчинг противоречий и пропуск неизменившихся пар
  - Тесты ручных мыслей с `source_text`, reader UI и повторного анализа при изменении источника
  - Тесты ручного создания/редактирования узлов и связей, reader tags/defaults и отказа от legacy-типов
  - Текущий набор: 103 автоматических теста

### Изменено
- **Breaking change / MVP data model**: Ручные связи приведены к MVP-набору `used_in`, `derived_from`, `contradicts`; legacy-типы вроде `related_to`, `supports`, `example_of`, `part_of` и `similar_to` больше не являются валидными.
- **Storage reset**: Для старых графов с legacy-типами рекомендуется очистить storage командой `python -m app.cli clear` перед запуском новой версии.
- **Manual capture defaults**: Выделенный фрагмент теперь создаёт `quote`, пользовательская мысль с `source_text` создаёт `idea`.
- **Graph UI**: Списки фильтров и визуальные классы обновлены под MVP 2-типы узлов и связей; интерфейс позволяет создавать узлы, редактировать выбранный узел и создавать ручную связь между двумя выбранными узлами.
- **LLM extraction**: Prompt/schema используют `used_in`, `derived_from`, `contradicts`; автоматические `source`-узлы запрещены и отбрасываются.
- **API responses**: Узлы и связи возвращают стандартизированные поля `trust_status`, `origin`, `review_status`, `user_comment`; связи также возвращают `edge_layer`, узлы возвращают `title` и `tags`.
- **API responses**: `/api/knowledge` и `/api/sources` возвращают `llm_status`, `warnings`, `errors`.
- **API responses**: Узлы также возвращают структурированную provenance-привязку; `source_text` сохранён для совместимости.
- **Proactive analysis**: Поиск похожих пар, embeddings, fingerprints и LLM-проверка противоречий учитывают `source_text` вместе с `content`
- **LLM extraction**: Удалён алгоритмический fallback; без LLM-клиента или при ошибке ответа извлечение возвращает пустой результат
- **Proactive digest**: Для противоречий в CLI-дайджесте выводятся оба исходных утверждения, которые сравнивал агент
- **Contradiction prompt**: Заголовок и объяснение противоречия запрашиваются на русском языке независимо от языка сравниваемых утверждений
- **Proactive analysis**: `analyze` строит похожие пары один раз, кэширует terms/embeddings в рамках запуска и переиспользует список кандидатов для скрытых связей и противоречий
- **Contradiction analysis**: OpenAI-compatible клиент получает батчи пар, а кастомный `detect_contradiction` остаётся совместимым с прежним попарным поведением
- **CLI add**: Команда `add` стала единой точкой добавления текста, UTF-8 файлов, нескольких файлов, stdin и текстовых URL; отдельная импортная команда удалена
- **Repository initialization**: Canonical `.graph.json` загружается первым, старый `.gexf` используется как fallback
- **Node.from_dict()**: Добавлена обработка служебных атрибутов NetworkX (label)

### Техническое
- **Стек технологий**:
  - Python 3.11+
  - NetworkX для хранения графа в памяти (MVP)
  - Подготовка к интеграции Neo4j для продакшена
  - FastAPI для API слоя
  - pytest для тестирования

---

## Формат
Этот файл ведётся в формате [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).

## Версионирование
Проект использует [SemVer](https://semver.org/lang/ru/) для версионирования.
