# Exocortex: руководство по запуску

## Что такое Exocortex?

Exocortex - персональная система управления знаниями на основе графа знаний и LLM. MVP умеет хранить узлы и связи, извлекать сущности из текста через настроенный LLM, работать через CLI и FastAPI.

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

### CLI

```bash
python -m app.cli --help
```

Команды:

```bash
python -m app.cli add "Python is a programming language. It is used for data analysis."
python -m app.cli add --file notes.txt --source-type note
type notes.txt | python -m app.cli add --stdin
python -m app.cli stats
python -m app.cli list --limit 20
python -m app.cli search Python
python -m app.cli forgotten --threshold 0.3
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

Директория создаётся автоматически при первом сохранении.

## REST API

Основные endpoints:

- `GET /` - статус API
- `POST /api/knowledge` - добавить текст и извлечь знания
- `GET /api/nodes` - список узлов, фильтр по `node_type` или `search`
- `GET /api/nodes/{node_id}` - узел по ID
- `GET /api/nodes/{node_id}/neighbors` - соседние узлы
- `GET /api/edges` - список связей
- `GET /api/stats` - статистика графа
- `GET /api/fragments` - исходные фрагменты
- `DELETE /api/nodes/{node_id}` - удалить узел
- `DELETE /api/edges/{edge_id}` - удалить связь

Пример:

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge ^
  -H "Content-Type: application/json" ^
  -d "{\"text\":\"Python is a programming language. It is used for data analysis.\"}"
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

## Тестирование

```bash
pytest tests/
```

Текущий набор проверяет модели, репозиторий, LLM-извлечение, API-конфигурацию и CLI.

## Статус MVP

Реализован Этап 1 и Этап 2:

- базовая структура проекта
- модели данных `Node`, `Edge`, `KnowledgeFragment`
- графовый репозиторий с CRUD, поиском, статистикой, forgotten nodes
- сохранение и загрузка GEXF + JSON-фрагментов
- LLM extraction pipeline без алгоритмического fallback-извлечения
- REST API
- CLI: `add`, `stats`, `list`, `search`, `forgotten`, `clear`
- запуск через `python -m app.main`
- Docker Compose
- 52 автоматических теста

Этап 3: проактивные агенты и автоматизация.
