# Exocortex: руководство по запуску

## Что такое Exocortex?

Exocortex - персональная система управления знаниями на основе графа знаний и LLM. MVP умеет хранить узлы и связи, извлекать сущности из текста через настроенный LLM, вручную сохранять выделенные фрагменты без LLM-обработки, анализировать граф проактивным агентом, формировать дайджесты инсайтов, принимать реакции пользователя, обновлять граф по feedback, строить базовый профиль интересов, импортировать внешние текстовые источники и работать через CLI/FastAPI.

## Требования

- Python 3.11 или выше
- pip
- Для извлечения нужен настроенный LLM-провайдер: hosted API с ключом или локальный Ollama
- Docker опционален

## Установка

### 1. Клонирование репозитория

```bash
git clone <repository-url>
cd Exocortex
```

### 2. Виртуальное окружение

```bash
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### 3. Зависимости

```bash
pip install -r requirements.txt
```

### 4. Конфигурация

```bash
cp config/.env.example config/.env
```

Настройте `config/.env`:

- `LLM_PROVIDER`: провайдер LLM, `openai` по умолчанию или `ollama` для локального агента
- `LLM_API_KEY`: API-ключ OpenAI или совместимого провайдера; для Ollama не нужен
- `LLM_MODEL`: модель, например `gpt-4o-mini` или локальная `llama3.1`
- `STORAGE_PATH`: путь к файлам графа без расширения, по умолчанию `data/graph`; относительные пути считаются от корня репозитория
- `LLM_API_BASE`: опциональный base URL для OpenAI-compatible API
- `OLLAMA_BASE_URL`: адрес локального Ollama, по умолчанию можно использовать `http://localhost:11434`
- `AGENT_ENABLED`: включить фоновый запуск проактивного агента вместе с API, по умолчанию `false`
- `AGENT_INTERVAL_MINUTES`: период фонового анализа графа, по умолчанию `1440` минут
- `AGENT_DIGEST_LIMIT`: максимум инсайтов в одном дайджесте, по умолчанию `3`
- `AGENT_FORGOTTEN_THRESHOLD`: порог силы памяти для напоминаний, по умолчанию `0.3`
- `AGENT_CONTRADICTION_BATCH_SIZE`: сколько похожих пар отправлять в один OpenAI-compatible prompt проверки противоречий, по умолчанию `8`

Код также понимает совместимые переменные `OPENAI_API_KEY` и `OPENAI_API_BASE`.

Пример для OpenRouter:

```env
LLM_API_BASE=https://openrouter.ai/api/v1
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
```

Пример для локального Ollama:

```bash
ollama pull llama3.1
```

```env
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
OLLAMA_BASE_URL=http://localhost:11434
```

Пример настроек проактивного агента:

```env
AGENT_ENABLED=true
AGENT_INTERVAL_MINUTES=1440
AGENT_DIGEST_LIMIT=3
AGENT_FORGOTTEN_THRESHOLD=0.3
AGENT_CONTRADICTION_BATCH_SIZE=8
```

## Запуск

### REST API

```bash
python -m app.main
```

По умолчанию сервер стартует на `http://127.0.0.1:8000`.

Полезные опции:

```bash
python -m app.main --host 0.0.0.0 --port 8000 --reload
```

Документация FastAPI доступна на `/docs`.
Встроенный inbox доступен на `/app`.
WEB-читалка для ручного выделения доступна на `/reader`.

### CLI

```bash
python -m app.cli --help
```

Команды:

```bash
python -m app.cli add "Python is a programming language. It is used for data analysis."
python -m app.cli add --file notes.txt --source-type note
type notes.txt | python -m app.cli add --stdin
python -m app.cli add-manual "Точный фрагмент для сохранения без LLM"
python -m app.cli add-manual --file selection.txt --source-url local:article.md --document-title article.md
python -m app.cli stats
python -m app.cli list --limit 20
python -m app.cli search Python
python -m app.cli forgotten --threshold 0.3
python -m app.cli analyze
python -m app.cli digest
python -m app.cli inbox
python -m app.cli react <insight_id> useful
python -m app.cli interests
python -m app.cli ingest --file notes.txt
python -m app.cli ingest --url https://example.com/article.txt
python -m app.cli clear
```

### Docker

```bash
docker-compose up -d
```

Контейнер читает `config/.env`, публикует API на `8000` и монтирует `./data` для сохранения графа.

## Хранение данных

Если `STORAGE_PATH=data/graph`, приложение создаёт:

- `data/graph.gexf` - граф знаний в формате GEXF
- `data/graph.fragments.json` - исходные фрагменты знаний
- `data/graph.insights.json` - сохранённые дайджесты проактивного агента
- `data/graph.feedback.json` - реакции пользователя на инсайты
- `data/graph.analysis_state.json` - состояние инкрементального анализа: fingerprints узлов и настроек агента

Директория создаётся автоматически при первом сохранении.

## REST API

Основные endpoints:

- `GET /` - статус API
- `GET /app` - встроенный web UI для inbox и реакций
- `GET /reader` - встроенная читалка для ручного сохранения выделенных фрагментов
- `POST /api/knowledge` - добавить текст и извлечь знания
- `POST /api/manual-fragments` - сохранить выделенный текст как узел `excerpt` без LLM-обработки
- `POST /api/sources` - импортировать внешний источник: прямой текст или текстовый URL
- `GET /api/nodes` - список узлов, фильтр по `node_type` или `search`
- `GET /api/nodes/{node_id}` - узел по ID
- `GET /api/nodes/{node_id}/neighbors` - соседние узлы
- `GET /api/edges` - список связей
- `GET /api/stats` - статистика графа
- `GET /api/fragments` - исходные фрагменты
- `POST /api/agent/analyze` - запустить проактивный анализ графа
- `GET /api/digest` - получить последний сохранённый дайджест
- `GET /api/insights` - получить инсайты из последнего дайджеста
- `GET /api/inbox` - получить inbox инсайтов со статусом реакции
- `POST /api/insights/{insight_id}/feedback` - сохранить реакцию на инсайт и обновить граф
- `GET /api/personalization` - получить базовый профиль интересов
- `DELETE /api/nodes/{node_id}` - удалить узел
- `DELETE /api/edges/{edge_id}` - удалить связь

Пример:

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Python is a programming language. It is used for data analysis.\"}"
```

Запуск проактивного анализа:

```bash
curl -X POST http://127.0.0.1:8000/api/agent/analyze
curl http://127.0.0.1:8000/api/digest
```

Реакция на инсайт:

```bash
curl http://127.0.0.1:8000/api/inbox
curl -X POST http://127.0.0.1:8000/api/insights/<insight_id>/feedback ^
  -H "Content-Type: application/json" ^
  -d "{\"action\":\"useful\"}"
curl http://127.0.0.1:8000/api/personalization
```

Ручное сохранение фрагмента без LLM:

```bash
curl -X POST http://127.0.0.1:8000/api/manual-fragments ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Этот фрагмент попадёт в граф без обработки моделью.\",\"source_type\":\"reader\",\"document_title\":\"notes.md\"}"
```

## Python API

```python
from app.core.repository import GraphRepository
from app.core.models import Node, NodeType

repo = GraphRepository("data/graph")
node = Node(
    content="Machine learning is a subfield of artificial intelligence",
    node_type=NodeType.CONCEPT,
)

repo.add_node(node)
repo.save()
```

## Проактивный агент

Агент анализирует граф и создаёт короткий дайджест из 1-3 инсайтов:

- `contradiction` - потенциальные противоречия между похожими утверждениями
- `hidden_connection` - неочевидные связи между похожими, но ещё не связанными узлами
- `reminder` - забываемый контент на основе `strength`, `decay_rate`, `last_interacted`

Разовый запуск:

```bash
python -m app.cli analyze
python -m app.cli digest
```

Фоновый запуск вместе с API включается через `AGENT_ENABLED=true`. По умолчанию агент не стартует автоматически, чтобы локальная разработка и тесты не создавали лишние фоновые задачи.

Повторный анализ оптимизирован:

- похожие пары узлов строятся один раз и переиспользуются для скрытых связей и противоречий
- terms и embeddings кэшируются в рамках одного запуска
- если LLM-клиент не настроен, проверка противоречий пропускается до лишней подготовки кандидатов
- OpenAI-compatible проверка противоречий использует батчи по `AGENT_CONTRADICTION_BATCH_SIZE` пар в одном prompt
- при запуске с сохранением агент пишет `.analysis_state.json` и в следующий раз пропускает пары, где оба узла и параметры анализа не изменились

Чтобы принудительно пересчитать все пары, удалите `<STORAGE_PATH>.analysis_state.json` или измените параметры анализа.

## Контур взаимодействия и персонализация

После генерации дайджеста инсайты попадают во встроенный inbox. Пользователь может реагировать на них через CLI или API:

- для `contradiction`: `choose_left`, `choose_right`, `resolved`, `keep_both`
- для `hidden_connection`: `confirm`, `reject`, `refine`
- для `reminder`: `useful`, `ignore`

CLI-пример:

```bash
python -m app.cli analyze
python -m app.cli inbox
python -m app.cli react <insight_id> useful
python -m app.cli interests
```

Реакции сохраняются в `.feedback.json`. Подтверждённые связи добавляются в граф, полезные напоминания усиливают соответствующие узлы, а отклонения и игнорирования учитываются в статистике. Профиль интересов показывает количество feedback-событий, популярные темы, взаимодействия с узлами и базовый стиль сообщений агента.

Проактивный агент использует этот профиль при генерации следующих дайджестов: повышает приоритет инсайтов по интересным темам и узлам, учитывает частоту полезных/отклонённых реакций по типам инсайтов и сокращает описания при стиле `concise`.

Web UI:

```bash
python -m app.main
```

Откройте `http://127.0.0.1:8000/app`.

Reader UI:

```bash
python -m app.main
```

Откройте `http://127.0.0.1:8000/reader`, загрузите UTF-8 текстовый или Markdown-файл, выделите фрагмент, нажмите правой кнопкой мыши и выберите `Add to Graph`. Читалка отправляет на сервер только выделенный текст, имя файла и смещения выделения; LLM при этом не вызывается.

## Внешние источники

Для импорта текстовых источников используйте CLI:

```bash
python -m app.cli ingest "Текст заметки для импорта"
python -m app.cli ingest --file notes.txt
python -m app.cli ingest --url https://example.com/article.txt
```

Или API:

```bash
curl -X POST http://127.0.0.1:8000/api/sources ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"External source content.\",\"source_type\":\"note\"}"
```

URL-импорт рассчитан на текстовые ответы. HTML пока сохраняется как полученный текст без отдельного парсинга статьи.

## Тестирование

```bash
pytest tests/
```

Если `pytest` не доступен в глобальном PATH, используйте Python из виртуального окружения:

```bash
venv\Scripts\python -m pytest -q     # Windows
python -m pytest -q                  # Linux/macOS после активации venv
```

Текущий набор проверяет модели, репозиторий, LLM-извлечение, API-конфигурацию, CLI, ручное добавление фрагментов, проактивного агента, батчинг и инкрементальность анализа, импорт источников, сохранение дайджестов, feedback-контур и персонализацию.

## Статус MVP

Реализованы Этап 1, Этап 2, Этап 3 и Этап 4:

- базовая структура проекта
- модели данных `Node`, `Edge`, `KnowledgeFragment`
- графовый репозиторий с CRUD, поиском, статистикой, forgotten nodes
- сохранение и загрузка GEXF + JSON-фрагментов
- LLM extraction pipeline без алгоритмического fallback-извлечения
- REST API
- CLI: `add`, `add-manual`, `stats`, `list`, `search`, `forgotten`, `analyze`, `digest`, `inbox`, `react`, `interests`, `ingest`, `clear`
- проактивный агент с поиском противоречий, неочевидных связей и забываемого контента
- оптимизированный анализ графа: общий подбор похожих пар, кэши terms/embeddings, батчинг LLM-противоречий и пропуск неизменившихся пар
- генерация и сохранение дайджестов инсайтов
- inbox инсайтов, реакции пользователя и обновление графа по feedback
- ручное сохранение выделенных фрагментов как узлов `excerpt` через API, CLI и `/reader`
- базовая модель интересов и статистика взаимодействий
- фоновый запуск агента через APScheduler
- локальные векторные эмбеддинги для семантического сравнения узлов
- импорт внешних текстовых источников через CLI/API
- запуск через `python -m app.main`
- Docker Compose
- 78 автоматических тестов

Следующий этап: доставка, мониторинг и подготовка к тестированию.
