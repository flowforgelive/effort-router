# effort-router

Автоматический выбор reasoning effort для субагентов в Claude Code, Codex и Antigravity CLI (agy).

Субагент по умолчанию наследует effort основной сессии. Если сессия работает на `xhigh` или `max`, на том же уровне идут и поиск по файлам, и переименование, и отладка гонки. Замер [effortmining](https://github.com/nagisanzenin/effortmining): тривиальные подзадачи на `low` проходят так же, как на `xhigh`, а `max` ни разу не обыграл `xhigh`, хотя тратит примерно в 7 раз больше токенов, чем `low`. effort-router запускает каждый субагент на минимально достаточном уровне и поднимает уровень только после проваленной проверки.

## Что умеет каждый хост

Механизмы проверены пробами, а не взяты из документации: там она расходится с поведением.

| Хост | Как задаётся effort субагента | Что делает effort-router |
|---|---|---|
| **Claude Code** | только `effort:` во frontmatter агента; у инструмента Agent параметра effort нет | лестница агентов `effort-low…xhigh` + `effort-scout`; хук `PreToolUse` переводит `general-purpose`/`Explore` на нужную ступень; скил |
| **Codex** | параметр `reasoning_effort` у `spawn_agent`. `model_reasoning_effort` в файле агента и `[agents] default_subagent_reasoning_effort` субагенту не передаются | инструкция в `~/.codex/AGENTS.md` + скил: оркестратор передаёт `reasoning_effort` по классу задачи |
| **agy** | только семейство модели: явное (`flash`) всегда запускается на `-low`, `inherit` = модель и effort родителя | плагин с хуком: задачи уровня `low` → `flash`, остальное наследует; правила; скил |
| **Grok Build** | ❌ у `spawn_subagent` нет ни модели, ни effort; поле effort в файле агента игнорируется | ничего: effort субагента = effort сессии |
| OpenCode | не проверено | пока не поддерживается |

## Установка

Нужен Python 3.9+ без сторонних пакетов.

```bash
git clone https://github.com/flowforgelive/effort-router.git ~/dev/effort-router
cd ~/dev/effort-router
python3 install.py --dry-run     # посмотреть, что изменится
python3 install.py               # установить во все найденные CLI
```

Установщик сам находит `claude`, `codex`, `agy`, `grok` и ставит только туда, где CLI есть. Повторный запуск обновляет установку, поэтому после `git pull` снова выполни `python3 install.py`. Чужие файлы он не перезаписывает, а каждый изменённый конфиг сначала копирует в `~/.local/state/effort-router/backups/<время>/`.

| Хост | Что ставится |
|---|---|
| Claude Code | плагин `effort-router@effort-router` из этого каталога как локального маркетплейса (`claude plugin marketplace add` + `claude plugin install`) |
| Codex | ссылка `~/.codex/skills/effort-routing` → `skills/effort-routing`; блок между маркерами `<!-- effort-router:begin/end -->` в `~/.codex/AGENTS.md` |
| agy | ссылка `~/.gemini/config/plugins/effort-router` → `hosts/agy` (внутри хук, правила и скил) |

После установки перезапусти открытые сессии этих CLI.

### Глобальные дефолты effort

```bash
python3 install.py --reset-effort-defaults
```

Удаляет закреплённый глобальный effort, после чего каждый CLI берёт дефолт своей модели и автоматически подхватывает новый при обновлении:
- `effortLevel` и `modelSettings.*.effortLevel` из `~/.claude/settings.json`;
- `model_reasoning_effort` верхнего уровня из `~/.codex/config.toml`;
- `[models] default_reasoning_effort` из `~/.grok/config.toml`.

Флаг необязателен. Меняется effort основной сессии, а не только субагентов.

### Удаление

```bash
python3 install.py uninstall
```

## Как это работает

Все правила лежат в одном файле, `policy.json`:
- **классы задач** со ступенью effort и сигналами на русском и английском: `scout`, `mechanical` → `low`, `implement` → `medium`, `debug` → `high`, `deep` → `xhigh`;
- **уровень по умолчанию** для неклассифицированных задач — `medium`;
- **порог `high`** для безопасности, конкурентности, миграций и прода;
- **потолок `xhigh`**: `max` субагентам не выдаётся.

1. **Классифицирует прежде всего оркестратор.** Скил `effort-routing` даёт ему таблицу классов и протокол: дешёвый уровень → проверка тестом или линтером → повтор на одну ступень выше, не больше двух раз.
2. **Хук — страховка.** Если оркестратор спавнит общего агента без выбранного уровня, хук определяет класс по тексту задачи и подменяет агента. Явный выбор агента или модели хук не трогает. При любой ошибке хук пропускает спавн без изменений. `EFFORT_ROUTER=off` отключает его.
3. **Лог решений** пишется в `~/.local/state/effort-router/dispatch.jsonl`: класс, уровень, что было запрошено и куда направлено. Это задел для будущей перекалибровки таблицы.

### Своя политика

Создай `~/.config/effort-router/policy.json` (или укажи путь в `EFFORT_ROUTER_POLICY`) и перечисли в нём только то, что меняешь. Словари сливаются с политикой репозитория, списки заменяются целиком:

```json
{
  "default_level": "high",
  "classes": { "implement": { "level": "high" } }
}
```

Хуки читают политику на каждом спавне, переустановка не нужна. Таблицу в инструкциях для Codex и agy генерирует `tools/render.py` из `policy.json` репозитория. Если меняешь `policy.json` в репозитории, запусти `python3 tools/render.py` и `python3 install.py`.

## Разработка

```bash
python3 -m unittest discover -s tests   # тесты
python3 tools/render.py --check         # таблицы совпадают с policy.json
claude plugin validate .                # манифест плагина
```

Идеи взяты у [effortmining](https://github.com/nagisanzenin/effortmining) (лестница агентов по уровням, откалиброванная таблица) и [claude-model-router-hook](https://github.com/tzachbon/claude-model-router-hook) (перезапись спавна хуком с пропуском при ошибке).
