# Exocortex

Exocortex - персональная система управления знаниями на базе графа знаний, LLM-извлечения и проактивного агента. MVP хранит фрагменты знаний, извлекает из них узлы и связи, отслеживает забываемый контекст, ищет скрытые связи и потенциальные противоречия, собирает дайджест инсайтов и принимает реакции пользователя через CLI, REST API и встроенный web UI.

## Что уже реализовано

- Граф знаний в памяти на NetworkX с сохранением в GEXF.
- Хранение исходных фрагментов, дайджестов и пользовательских реакций в JSON.
- LLM-пайплайн извлечения сущностей и отношений из текста.
- Ручное сохранение выделенных фрагментов как `excerpt`-узлов без LLM-обработки.
- Поддержка OpenAI-compatible провайдеров и локального Ollama.
- CLI для добавления данных, просмотра графа, запуска агента и реакции на инсайты.
- FastAPI REST API.
- Встроенный web UI `/app` для inbox, реакций и профиля интересов.
- Простая web-читалка `/reader` для локальных UTF-8 текстовых и Markdown-файлов.
- Проактивный агент:
  - напоминания о забываемых узлах;
  - поиск похожих, но не связанных узлов;
  - батчевая LLM-проверка потенциальных противоречий;
  - инкрементальный повторный анализ неизменившегося графа;
  - приоритизация дайджеста;
  - адаптация по истории feedback.
- Базовая персонализация:
  - счётчики реакций;
  - популярные темы;
  - взаимодействия с узлами;
  - стиль сообщений `balanced`, `exploratory` или `concise`.

## Архитектура

Основные модули:

- `app/core/models.py` - модели `Node`, `Edge`, `KnowledgeFragment`, перечисления типов узлов и связей.
- `app/core/repository.py` - графовый репозиторий, CRUD, поиск, статистика, сохранение и загрузка.
- `app/llm/extraction.py` - LLM-извлечение сущностей и связей из текста.
- `app/agents/proactive.py` - проактивный агент и генерация инсайтов.
- `app/agents/insights.py` - модели `Insight`, `Digest` и JSON-хранилище дайджестов.
- `app/agents/embeddings.py` - локальные deterministic embeddings для сравнения текстов.
- `app/agents/scheduler.py` - фоновый запуск агента через APScheduler.
- `app/services/personalization.py` - inbox, feedback, обновление графа и профиль интересов.
- `app/services/external_sources.py` - импорт текста, UTF-8 файлов и текстовых URL.
- `app/services/manual_capture.py` - ручное сохранение выделенного текста без LLM.
- `app/api/routes.py` - REST API и выдача web UI.
- `app/cli.py` - CLI-команды.
- `app/main.py` - запуск FastAPI-сервера.

## Модель данных

### Узлы

Узел `Node` хранит отдельную единицу знания:

- `id` - UUID.
- `node_type` - тип узла.
- `content` - текстовое содержание.
- `source_text` - редактируемый исходный абзац, цитата или другой контекст, на котором основан узел; агент учитывает это поле при поиске скрытых связей и противоречий.
- `metadata` - источник, исходное имя сущности, confidence, тема, feedback-метаданные.
- `strength` - сила памяти от `0` до `1`.
- `decay_rate` - скорость забывания в день.
- `last_interacted` - последнее взаимодействие.
- `created_at` - дата создания.
- `embeddings` - локальный вектор для семантического сравнения.

Типы узлов:

| Тип | Назначение |
| --- | --- |
| `fact` | Конкретный факт. |
| `excerpt` | Фрагмент текста, вручную выделенный пользователем. |
| `concept` | Абстрактная концепция. |
| `thesis` | Тезис или утверждение. |
| `definition` | Определение термина. |
| `question` | Вопрос. |
| `source` | Источник информации. |

### Связи

Связь `Edge` соединяет два узла:

- `id` - UUID связи.
- `source_id` и `target_id` - узлы-участники.
- `edge_type` - тип отношения.
- `weight` - вес или уверенность связи.
- `metadata` - описание, источник, feedback-метаданные.
- `created_at` - дата создания.

Типы связей:

| Тип | Назначение |
| --- | --- |
| `related_to` | Общая смысловая связь. |
| `contradicts` | Противоречие. |
| `supports` | Поддержка или подтверждение. |
| `example_of` | Пример более общей идеи. |
| `part_of` | Часть целого. |
| `derived_from` | Выведено из другого знания. |
| `similar_to` | Похоже на другой узел. |

### Фрагменты

`KnowledgeFragment` хранит исходный текст, из которого были извлечены узлы:

- `content` - полный текст.
- `source_type` - `manual`, `chat`, `article`, `note`, `file`, `url`, `external` или другой пользовательский ярлык.
- `source_url` - URL или путь источника.
- `extracted_nodes` - ID созданных узлов.
- `created_at` - дата добавления.

При ручном добавлении мысли с источником `Node.content` хранит мысль пользователя, `Node.source_text` хранит цитату/абзац-основание, а `KnowledgeFragment.content` сохраняет источник как provenance-журнал добавления.

## Установка

Требования:

- Python 3.11 или выше.
- `pip`.
- LLM-провайдер для извлечения знаний: hosted OpenAI-compatible API или локальный Ollama.
- Docker опционален.

```bash
git clone <repository-url>
cd Exocortex
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Для Linux/macOS:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Конфигурация

Создайте `config/.env` из примера:

```bash
copy config\.env.example config\.env
```

Для Linux/macOS:

```bash
cp config/.env.example config/.env
```

Поддерживаемые переменные:

| Переменная | Описание |
| --- | --- |
| `STORAGE_PATH` | Путь к файлам графа без расширения. По умолчанию `data/graph`. Относительные пути считаются от корня проекта. |
| `LLM_PROVIDER` | `openai` по умолчанию, `ollama` или совместимый `local` alias. |
| `LLM_API_KEY` | API-ключ hosted провайдера. Для Ollama не нужен. |
| `OPENAI_API_KEY` | Совместимый alias для `LLM_API_KEY`. |
| `LLM_MODEL` | Модель для извлечения и проверки противоречий. |
| `OLLAMA_MODEL` | Alias модели для Ollama, если `LLM_MODEL` не задан. |
| `LLM_API_BASE` | Base URL для OpenAI-compatible API. |
| `OPENAI_API_BASE` | Совместимый alias для `LLM_API_BASE`. |
| `OLLAMA_BASE_URL` | URL Ollama, например `http://localhost:11434`. Код добавит `/v1`, если его нет. |
| `AGENT_ENABLED` | Запускать ли фонового агента вместе с API. По умолчанию `false`. |
| `AGENT_INTERVAL_MINUTES` | Интервал фонового анализа. По умолчанию `1440`. |
| `AGENT_DIGEST_LIMIT` | Максимум инсайтов в дайджесте. По умолчанию `3`. |
| `AGENT_FORGOTTEN_THRESHOLD` | Порог забывания для reminder-инсайтов. По умолчанию `0.3`. |
| `AGENT_CONTRADICTION_BATCH_SIZE` | Сколько похожих пар отправлять в один OpenAI-compatible prompt проверки противоречий. По умолчанию `8`. |

Пример OpenAI-compatible провайдера:

```env
LLM_PROVIDER=openai
LLM_API_KEY=<key>
LLM_MODEL=gpt-4o-mini
```

Пример OpenRouter:

```env
LLM_PROVIDER=openai
LLM_API_KEY=<key>
LLM_API_BASE=https://openrouter.ai/api/v1
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
```

Пример Ollama:

```bash
ollama pull llama3.1
```

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
OLLAMA_BASE_URL=http://localhost:11434
```

Важно: в проекте нет алгоритмического fallback-извлечения. Если LLM-клиент не настроен или запрос к модели завершился ошибкой, фрагмент будет сохранён, но `nodes_created` и `edges_created` будут равны `0`.

## Запуск

### API и web UI

```bash
python -m app.main
```

По умолчанию сервер доступен на `http://127.0.0.1:8000`.

Опции запуска:

| Опция | Описание |
| --- | --- |
| `--host` | Адрес, на котором слушает Uvicorn. По умолчанию `127.0.0.1`. |
| `--port` | Порт. По умолчанию `8000`. |
| `--reload` | Включить авто-перезагрузку при изменениях кода. |

Пример:

```bash
python -m app.main --host 0.0.0.0 --port 8000 --reload
```

Страницы:

- `http://127.0.0.1:8000/docs` - Swagger UI FastAPI.
- `http://127.0.0.1:8000/app` - встроенный inbox.
- `http://127.0.0.1:8000/reader` - web-читалка для сохранения выделений и мыслей с источниками.

### Docker

```bash
docker-compose up -d
```

Контейнер читает `config/.env`, публикует API на порту `8000` и монтирует `./data` для сохранения графа.

## CLI

Общий формат:

```bash
python -m app.cli <command> [options]
```

Справка:

```bash
python -m app.cli --help
python -m app.cli <command> --help
```

### `add`

Добавляет прямой текст, UTF-8 файлы или текстовые URL через LLM-пайплайн, создаёт `KnowledgeFragment`, узлы и связи, затем сохраняет граф.

```bash
python -m app.cli add "Python is a programming language. It is used for data analysis."
python -m app.cli add --file notes.txt
python -m app.cli add --file a.txt --file b.txt
python -m app.cli add --url https://example.com/article.txt
type notes.txt | python -m app.cli add --stdin
```

Аргументы и опции:

| Параметр | Описание |
| --- | --- |
| `text` | Текст из позиционных аргументов. Можно передавать несколько слов или предложений. |
| `--file <path>` | Прочитать UTF-8 файл. Можно передавать несколько раз. |
| `--url <url>` | Загрузить текстовый URL. Можно передавать несколько раз. |
| `--stdin` | Прочитать текст из stdin. |
| `--source-type <type>` | Переопределить ярлык источника. По умолчанию `manual` для текста/stdin, `file` для файлов, `url` для URL. |
| `--source-url <url>` | URL источника для прямого текста и stdin. |

Для `--file` по умолчанию используется `source_type=file`, `source_url=<path>`. Для `--url` по умолчанию используется `source_type=url`, `source_url=<url>`. URL-импорт читает тело ответа как текст; HTML пока сохраняется как полученный текст без отдельного парсинга статьи.

Выводит ID созданного фрагмента или список фрагментов, количество созданных узлов и общее число узлов.

### `add-manual`

Сохраняет текст как один узел без LLM-извлечения. Без `--source-text` команда создаёт `excerpt`; с `--source-text` создаёт `thesis`, где `content` - мысль, а `source_text` - исходная цитата или абзац.

```bash
python -m app.cli add-manual "Точный фрагмент, выбранный пользователем."
python -m app.cli add-manual "Моя мысль по прочитанному." --source-text "Абзац книги, на котором основана мысль."
python -m app.cli add-manual --file selection.txt --source-url local:article.md --document-title article.md
type selection.txt | python -m app.cli add-manual --stdin
```

Аргументы и опции:

| Параметр | Описание |
| --- | --- |
| `text` | Выделенный текст из позиционных аргументов. |
| `--file <path>` | Прочитать UTF-8 файл с уже выбранным фрагментом. |
| `--stdin` | Прочитать выделенный фрагмент из stdin. |
| `--source-type <type>` | Ярлык источника. По умолчанию `manual_selection`. |
| `--source-url <url>` | URL или путь документа-источника. |
| `--document-title <title>` | Название документа-источника. |
| `--source-text <text>` | Исходная цитата/абзац для создаваемой мысли. |

Команда создаёт один `KnowledgeFragment`, один `Node`, не создаёт связей и не обращается к LLM.

### `stats`

Показывает статистику графа:

```bash
python -m app.cli stats
```

Выводит:

- число узлов;
- число связей;
- число фрагментов;
- число забытых узлов;
- среднюю силу памяти;
- распределение по типам узлов;
- распределение по типам связей.

### `list`

Показывает узлы графа:

```bash
python -m app.cli list
python -m app.cli list --limit 20
```

Опции:

| Параметр | Описание |
| --- | --- |
| `--limit <n>` | Максимум узлов в выводе. По умолчанию `50`. |

Для каждого узла выводятся ID, тип, текущая сила памяти и содержание.

### `search`

Ищет узлы простым регистронезависимым текстовым поиском по `content`:

```bash
python -m app.cli search Python
python -m app.cli search "data analysis" --limit 10
```

Параметры:

| Параметр | Описание |
| --- | --- |
| `query` | Строка поиска. |
| `--limit <n>` | Максимум результатов. По умолчанию `50`. |

### `forgotten`

Показывает узлы, у которых текущая сила памяти ниже порога:

```bash
python -m app.cli forgotten
python -m app.cli forgotten --threshold 0.3 --limit 20
```

Параметры:

| Параметр | Описание |
| --- | --- |
| `--threshold <float>` | Порог забывания. По умолчанию `0.3`. |
| `--limit <n>` | Максимум результатов. По умолчанию `50`. |

Сила памяти считается по экспоненциальной модели:

```text
current_strength = strength * e^(-decay_rate * days_since_last_interaction)
```

### `analyze`

Запускает проактивного агента один раз:

```bash
python -m app.cli analyze
python -m app.cli analyze --no-save
```

Агент:

- ищет забываемый контент;
- ищет похожие несвязанные узлы;
- проверяет кандидаты на противоречия через LLM;
- сортирует инсайты по приоритету;
- формирует компактный дайджест.

Опции:

| Параметр | Описание |
| --- | --- |
| `--no-save` | Не сохранять сгенерированный дайджест в `.insights.json`. |

Приоритет типов в дайджесте: `contradiction` выше `reminder`, `reminder` выше `hidden_connection`.

### `digest`

Показывает последний сохранённый дайджест:

```bash
python -m app.cli digest
```

Если дайджеста ещё нет, выводит `No saved digest found.`

### `inbox`

Показывает сохранённые инсайты со статусом реакции:

```bash
python -m app.cli inbox
python -m app.cli inbox --include-reacted --limit 100
```

Параметры:

| Параметр | Описание |
| --- | --- |
| `--limit <n>` | Максимум элементов. По умолчанию `50`. |
| `--include-reacted` | Включить инсайты, на которые уже была реакция. Без флага показываются только pending-инсайты. |

Для каждого элемента выводятся ID инсайта, тип, статус, score, заголовок и описание.

### `react`

Сохраняет реакцию на инсайт и применяет её к графу:

```bash
python -m app.cli react <insight_id> useful
python -m app.cli react <insight_id> refine --note "Связь скорее про retrieval practice"
```

Параметры:

| Параметр | Описание |
| --- | --- |
| `insight_id` | ID инсайта из `digest`, `inbox` или API. |
| `action` | Действие пользователя. Доступный набор зависит от типа инсайта. |
| `--note <text>` | Необязательная заметка или уточнение. |

Доступные действия:

| Тип инсайта | Действия |
| --- | --- |
| `contradiction` | `choose_left`, `choose_right`, `resolved`, `keep_both` |
| `hidden_connection` | `confirm`, `reject`, `refine` |
| `reminder` | `useful`, `ignore` |

Эффекты feedback:

- `choose_left` и `choose_right` усиливают выбранный узел, помечают второй как отвергнутый после противоречия и создают или обновляют связь `contradicts`.
- `resolved` помечает оба узла как обработанные и создаёт или обновляет связь `contradicts`.
- `keep_both` помечает оба узла и создаёт или обновляет связь `contradicts` с меньшим весом.
- `confirm` создаёт или обновляет связь `related_to` с весом `0.9`, усиливает оба узла.
- `refine` создаёт или обновляет связь `related_to` с весом `0.7`, сохраняет `--note` как уточнение, усиливает оба узла.
- `reject` помечает оба узла как `connection_rejected` и снижает `interest_score`.
- `useful` вызывает `node.interact()`: увеличивает `strength` на `0.1` до максимума `1.0`, обновляет `last_interacted`, повышает `interest_score`.
- `ignore` помечает узел как `reminder_ignored` и снижает `interest_score`.

### `interests`

Показывает базовый профиль интересов:

```bash
python -m app.cli interests
```

Выводит:

- общее число feedback-событий;
- число позитивных реакций;
- число негативных реакций;
- текущий стиль сообщений;
- топ тем, вычисленный по узлам, участвовавшим в feedback.

Стиль сообщений:

- `balanced` - режим по умолчанию;
- `exploratory` - включается при нескольких позитивных реакциях;
- `concise` - включается, если негативных реакций больше позитивных.

### `clear`

Удаляет сохранённые файлы текущего хранилища:

```bash
python -m app.cli clear
```

Удаляются:

- `<STORAGE_PATH>.gexf`;
- `<STORAGE_PATH>.fragments.json`;
- `<STORAGE_PATH>.insights.json`;
- `<STORAGE_PATH>.feedback.json`;
- `<STORAGE_PATH>.analysis_state.json`.

Команда выводит количество удалённых файлов.

## Web UI

Встроенный UI доступен после запуска API:

```bash
python -m app.main
```

Откройте:

```text
http://127.0.0.1:8000/app
```

Основной inbox доступен на `/app` и состоит из списка инсайтов и панели персонализации.

### Верхняя панель

| Действие | Что делает |
| --- | --- |
| `Pending` | Показывает только инсайты без реакции. Вызывает `/api/inbox?include_reacted=false`. |
| `All` | Показывает все инсайты, включая уже обработанные. Вызывает `/api/inbox?include_reacted=true`. |
| `Run Analysis` | Запускает агента через `POST /api/agent/analyze`, сохраняет новый дайджест и обновляет экран. |
| `Refresh` | Перезагружает inbox и профиль интересов без запуска нового анализа. |

### Карточка инсайта

Каждая карточка показывает:

- тип инсайта: `contradiction`, `hidden_connection` или `reminder`;
- короткий ID;
- `score`;
- статус `pending` или последнюю реакцию;
- заголовок;
- описание;
- поле `Note`;
- кнопки действий.

Поле `Note` отправляется вместе с реакцией и сохраняется в feedback. Для `refine` заметка также попадает в metadata связи как уточнение.

### Действия для `contradiction`

`contradiction` - потенциальное противоречие между двумя узлами.

| Кнопка | API action | Эффект |
| --- | --- | --- |
| `Choose A` | `choose_left` | Принимает первый узел, помечает второй как отвергнутый после противоречия, создаёт или обновляет связь `contradicts`. |
| `Choose B` | `choose_right` | Принимает второй узел, помечает первый как отвергнутый после противоречия, создаёт или обновляет связь `contradicts`. |
| `Resolved` | `resolved` | Помечает оба узла как обработанные, создаёт или обновляет связь `contradicts`. |
| `Keep Both` | `keep_both` | Сохраняет оба утверждения как конкурирующие версии, создаёт или обновляет связь `contradicts` с весом `0.6`. |

### Действия для `hidden_connection`

`hidden_connection` - возможная связь между похожими узлами, которые ещё не соединены ребром.

| Кнопка | API action | Эффект |
| --- | --- | --- |
| `Confirm` | `confirm` | Создаёт или обновляет связь `related_to` с весом `0.9`, усиливает оба узла. |
| `Reject` | `reject` | Помечает узлы как `connection_rejected`, снижает их `interest_score`. |
| `Refine` | `refine` | Создаёт или обновляет связь `related_to` с весом `0.7`, сохраняет заметку как уточнение, усиливает оба узла. |

### Действия для `reminder`

`reminder` - напоминание о знании, сила памяти которого опустилась ниже порога.

| Кнопка | API action | Эффект |
| --- | --- | --- |
| `Useful` | `useful` | Увеличивает силу памяти узла, обновляет `last_interacted`, повышает `interest_score`. |
| `Ignore` | `ignore` | Помечает узел как `reminder_ignored`, снижает `interest_score`. |

После реакции кнопки карточки становятся недоступными, а статус меняется на выбранное действие.

### Панель Personalization

Панель справа показывает:

- `Feedback` - общее число реакций.
- `Positive` - количество позитивных реакций.
- `Negative` - количество негативных реакций.
- `Topics` - количество тем в топе.
- `Top Topics` - темы, полученные из metadata узлов или текста узлов.
- бейдж стиля сообщений: `balanced`, `exploratory` или `concise`.

Профиль используется агентом при следующей генерации дайджеста: повышаются scores инсайтов по интересным темам и узлам, учитывается история полезных и отклонённых реакций, а при стиле `concise` описание инсайтов укорачивается.

### Reader

Читалка доступна на:

```text
http://127.0.0.1:8000/reader
```

MVP-читалка работает с локальными UTF-8 текстовыми, Markdown и HTML-файлами как с plain text. Файл читается в браузере через `FileReader` и не загружается на сервер целиком. На сервер отправляется только выбранный фрагмент или введённая мысль с редактируемым источником.

Действия:

| Действие | Что делает |
| --- | --- |
| `Open File` | Открывает локальный файл и показывает его текст в области чтения. |
| Выделение текста + правый клик | Показывает всплывающее меню рядом с выделением. |
| `Add to Graph` | Отправляет выделенный текст в `POST /api/manual-fragments` и сохраняет его как `excerpt`. |
| `Add as Source` | Кладёт выделенный текст в редактируемое поле `Source` в правой панели. |
| `Add Selection` | Сохраняет текущее выделение без контекстного меню. |
| `Add Thought` | Сохраняет текст из поля `Thought` как `thesis`; поле `Source` отправляется как `source_text`. |
| `Hide` / `Show` | Скрывает или показывает поле источника в панели мысли. |
| `Clear` | Очищает читалку и текущие metadata файла. |
| `Inbox` | Переходит на `/app`. |

При сохранении читалка передаёт:

- точный выделенный текст;
- `source_type=reader`;
- `source_url=local:<file-name>`;
- `document_title=<file-name>`;
- для быстрого сохранения выделения: metadata файла и смещения `offset_start`, `offset_end`, `selected_length`;
- для мысли с источником: `text=<мысль>`, `source_text=<источник>`, `node_type=thesis`, а также metadata смещения источника `source_offset_start`, `source_offset_end`, `source_selected_length`, если источник был взят из выделения.

Сохранённый узел сразу участвует в следующем анализе. Агент сравнивает не только `content`, но и `source_text`, поэтому источники помогают находить скрытые зависимости и противоречия.

## REST API

Swagger доступен на `/docs`.

| Метод | Endpoint | Назначение |
| --- | --- | --- |
| `GET` | `/` | Проверка API, ссылки на `/docs`, `/app` и `/reader`. |
| `GET` | `/app` | Встроенный web UI. |
| `GET` | `/reader` | Web-читалка для ручного сохранения выделений и мыслей с источниками. |
| `POST` | `/api/knowledge` | Добавить текст, извлечь знания через LLM, сохранить фрагмент, узлы и связи. |
| `POST` | `/api/sources` | Импортировать прямой текст или текстовый URL. |
| `POST` | `/api/manual-fragments` | Сохранить выделенный текст как `excerpt` или мысль с `source_text` как `thesis` без LLM-обработки. |
| `GET` | `/api/nodes` | Получить список узлов. Поддерживает `node_type`, `search`, `limit`. |
| `GET` | `/api/nodes/{node_id}` | Получить узел по ID. |
| `GET` | `/api/nodes/{node_id}/neighbors` | Получить соседей узла. Поддерживает `radius`. |
| `GET` | `/api/edges` | Получить связи. Поддерживает `edge_type` и `limit`; `edge_type=contradicts` возвращает только противоречия. |
| `GET` | `/api/stats` | Статистика графа. |
| `GET` | `/api/fragments` | Список исходных фрагментов. Поддерживает `limit`. |
| `POST` | `/api/agent/analyze` | Запустить агента, сохранить дайджест и вернуть его. |
| `GET` | `/api/digest` | Получить последний сохранённый дайджест. |
| `GET` | `/api/insights` | Получить инсайты из последнего дайджеста. |
| `GET` | `/api/inbox` | Получить inbox. Поддерживает `include_reacted` и `limit`. |
| `POST` | `/api/insights/{insight_id}/feedback` | Сохранить реакцию и обновить граф. |
| `GET` | `/api/personalization` | Получить профиль интересов. |
| `DELETE` | `/api/nodes/{node_id}` | Удалить узел. |
| `DELETE` | `/api/edges/{edge_id}` | Удалить связь. |

Пример добавления знания:

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Python is a programming language. It is used for data analysis.\",\"source_type\":\"note\"}"
```

Пример ручного добавления без LLM:

```bash
curl -X POST http://127.0.0.1:8000/api/manual-fragments ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Этот фрагмент сохранится в граф в исходном виде.\",\"source_type\":\"reader\",\"document_title\":\"notes.md\"}"
```

Пример ручной мысли с источником:

```bash
curl -X POST http://127.0.0.1:8000/api/manual-fragments ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Моя мысль по прочитанному.\",\"source_text\":\"Абзац книги, на котором основана мысль.\",\"node_type\":\"thesis\",\"source_type\":\"reader\",\"document_title\":\"book.md\"}"
```

Пример запуска анализа:

```bash
curl -X POST http://127.0.0.1:8000/api/agent/analyze
curl http://127.0.0.1:8000/api/inbox
```

Пример реакции:

```bash
curl -X POST http://127.0.0.1:8000/api/insights/<insight_id>/feedback ^
  -H "Content-Type: application/json" ^
  -d "{\"action\":\"useful\",\"note\":\"Нужно повторить позже\"}"
```

## Проактивный агент

Агент запускается вручную через CLI/API или в фоне вместе с сервером, если `AGENT_ENABLED=true`.

Алгоритм анализа:

1. `find_forgotten_content` выбирает узлы ниже `AGENT_FORGOTTEN_THRESHOLD`.
2. Агент один раз строит список похожих пар по лексическому сходству и локальным embeddings, учитывая `content` и `source_text`.
3. `find_hidden_connections` использует этот список и отбрасывает пары, где уже есть прямое ребро.
4. `find_contradictions` использует тот же список и проверяет похожие пары через LLM. В prompt попадает утверждение и источник/контекст, если у узла есть `source_text`. Для OpenAI-compatible клиента несколько пар отправляются в одном prompt с JSON-массивом результатов.
5. `generate_digest` применяет персонализацию, сортирует инсайты и обрезает список до `AGENT_DIGEST_LIMIT`.
6. Дайджест сохраняется в `<STORAGE_PATH>.insights.json`, если запуск был с сохранением.
7. Состояние анализа сохраняется в `<STORAGE_PATH>.analysis_state.json`; следующий запуск пропускает пары, где оба узла и параметры анализа не изменились.

Если LLM-клиент не настроен, агент пропускает проверку противоречий до построения LLM-кандидатов и всё равно может создавать `reminder` и `hidden_connection`.

Типы инсайтов:

| Тип | Как возникает |
| --- | --- |
| `reminder` | Узел считается забытым: текущая сила памяти ниже порога. |
| `hidden_connection` | Два похожих узла не имеют прямой связи. |
| `contradiction` | LLM подтвердил противоречие между похожими утверждениями. |

Для фонового запуска:

```env
AGENT_ENABLED=true
AGENT_INTERVAL_MINUTES=1440
AGENT_DIGEST_LIMIT=3
AGENT_FORGOTTEN_THRESHOLD=0.3
AGENT_CONTRADICTION_BATCH_SIZE=8
```

## Хранение данных

Если `STORAGE_PATH=data/graph`, будут созданы файлы:

| Файл | Содержимое |
| --- | --- |
| `data/graph.gexf` | Граф знаний: узлы и связи. |
| `data/graph.fragments.json` | Исходные фрагменты знаний. |
| `data/graph.insights.json` | Сохранённые дайджесты агента. |
| `data/graph.feedback.json` | Реакции пользователя на инсайты. |
| `data/graph.analysis_state.json` | Fingerprints узлов и настроек анализа для пропуска неизменившихся пар при повторном запуске агента. |

Директория хранения создаётся автоматически при сохранении.

## Python API

Минимальный пример прямой работы с репозиторием:

```python
from app.core.models import Node, NodeType
from app.core.repository import GraphRepository

repo = GraphRepository("data/graph")
node = Node(
    content="Machine learning is a subfield of artificial intelligence",
    node_type=NodeType.CONCEPT,
    source_text="Source paragraph or note that supports the node.",
)

repo.add_node(node)
repo.save()
```

## Тестирование

```bash
pytest tests/
```

Если `pytest` не доступен в PATH:

```bash
venv\Scripts\python -m pytest -q
```

Для Linux/macOS после активации окружения:

```bash
python -m pytest -q
```

Тесты покрывают модели, репозиторий, LLM-извлечение, CLI, API, ручные мысли с источниками, проактивного агента, батчинг и инкрементальность анализа, импорт источников, web UI, feedback и персонализацию.

## Текущий статус MVP

Завершены этапы 1-4:

- базовая структура проекта;
- модели данных и графовый репозиторий;
- сохранение GEXF и JSON;
- LLM extraction без fallback;
- CLI;
- REST API;
- ручное добавление `excerpt`-фрагментов и `thesis`-мыслей с `source_text` без LLM;
- проактивный агент;
- оптимизация анализа графа: общий подбор похожих пар, кэши terms/embeddings, батчинг LLM-проверки противоречий и инкрементальное состояние анализа;
- дайджесты инсайтов;
- inbox, feedback и обновление графа;
- базовая персонализация;
- встроенный web UI `/app`;
- web-читалка `/reader` с панелью мысли и редактируемым источником;
- фоновый запуск агента;
- Docker Compose;
- автоматические тесты.

Следующий этап по `PROGRESS.md`: доставка, мониторинг, документация и подготовка к пользовательской проверке.

Дополнительные документы:

- [EXOCORTEX.md](EXOCORTEX.md) - продуктовая концепция и границы MVP.
- [SETUP.md](SETUP.md) - руководство по запуску.
- [MVP_PLAN.md](MVP_PLAN.md) - план MVP.
- [PROGRESS.md](PROGRESS.md) - прогресс реализации.
- [CHANGELOG.md](CHANGELOG.md) - история изменений.
