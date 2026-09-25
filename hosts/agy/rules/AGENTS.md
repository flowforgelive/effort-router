# Effort субагентов (effort-router)

У `invoke_subagent` выбирается только семейство модели: явное (`flash`, `pro`) всегда запускается на `-low`, `inherit` — на модели и effort родителя. Хук плагина effort-router сам ставит `flash` подзадачам уровня `low` (разведка, механические правки). Для трудной работы оставляй `inherit`.

<!-- effort-router:classes:begin -->
| Класс | Уровень | Когда | Claude Code | Codex `spawn_agent` | agy `invoke_subagent` |
|---|---|---|---|---|---|
| `scout` | `low` | Разведка: найти файлы и определения, перечислить использования, описать структуру каталогов. Вывод — пути и строки, без суждений. | `effort-router:effort-scout` + `model: "haiku"` | `reasoning_effort: "low"` | `Model: "flash"` |
| `mechanical` | `low` | Механическая правка по точной инструкции: переименовать, отформатировать, поднять версию, поправить импорт или опечатку. | `effort-router:effort-low` + `model: "sonnet"` | `reasoning_effort: "low"` | `Model: "flash"` |
| `implement` | `medium` | Обычная реализация: написать функцию, тест, эндпоинт, экран; рефакторинг в пределах модуля по понятной задаче. | `effort-router:effort-medium` | `reasoning_effort: "medium"` | `Model: "inherit"` |
| `debug` | `high` | Диагностика: почему падает тест или сборка, разбор стектрейса, регрессия, флейки, поиск корневой причины. | `effort-router:effort-high` | `reasoning_effort: "high"` | `Model: "inherit"` |
| `deep` | `xhigh` | Глубокое рассуждение: архитектура и компромиссы, ревью сложного изменения, безопасность, конкурентность, тонкая алгоритмика. | `effort-router:effort-xhigh` | `reasoning_effort: "xhigh"` | `Model: "inherit"` |

Класс не ясен — уровень `medium`. Минимум `high` — ошибка здесь не видна сразу и дорого стоит: безопасность, конкурентность, миграции данных, прод. Потолок для субагентов — `xhigh` (`max` не используется).
<!-- effort-router:classes:end -->

Сначала дешёвый уровень, потом проверка тестом или линтером, эскалация только после провала. Подробности — в скиле `effort-routing`.
