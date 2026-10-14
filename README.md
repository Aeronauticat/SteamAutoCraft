# SteamAutoCraft

**自动补齐 Steam 集换式卡牌，为合成徽章做准备。**  
**Buy missing Steam trading cards to prepare for badge crafting.**

`HKD` · `macOS / Linux` · `Python` · `main.py`

[使用 / Setup](#setup) · [配置 / Configuration](#configuration) · [运行 / Run](#run) · [进度 / Progress](#progress)

根据已有徽章、库存和实时市场挂单，计算补齐每套普通卡牌的成本，再按预算提交买单。已有卡牌会从需求中扣除，最多规划到普通徽章 5 级。徽章需在 Steam 中手动合成。

Reads badges, inventory and live market listings, calculates the cost of completing each regular card set, then submits buy orders according to the configured budgets. Owned cards reduce the purchase quantity; planning stops at regular badge level 5. Craft badges manually in Steam.

> **真实交易 / Live purchases**  
> 启动后会使用 Steam 钱包下单，没有预览模式。当前代码按港区及 HKD 定价，仅适用于 HKD 钱包。  
> Running the script places real orders using the Steam wallet. There is no dry-run mode. Market requests and prices use the Hong Kong region and HKD; use an HKD wallet.

<a id="setup"></a>

## 使用 / Setup

### 1. 安装 / Install

使用 macOS 或 Linux、Python 3，以及能够使用社区市场的 Steam 账号。程序使用 Unix 文件锁，不支持直接在 Windows Python 中运行。

Use macOS or Linux, Python 3, and a Steam account with Community Market access. The script uses Unix file locking and does not run directly in Windows Python.

```bash
git clone --branch master https://github.com/Aeronauticat/SteamAutoCraft.git
cd SteamAutoCraft
python3 -m venv .venv
source .venv/bin/activate
python -m pip install "steampy>=1.2.0" "requests>=2.28.0" "pandas>=1.5.0" "pyyaml>=6.0"
mkdir -p config data
```

### 2. 准备本地文件 / Prepare local files

首次使用时复制以下示例，再填写实际内容。`cp -n` 不覆盖已有文件。真实配置和购买清单保留在本地，版本库只维护示例。

On first use, copy these examples and fill in the actual values. `cp -n` preserves existing files. Keep real configuration and game lists local; only examples belong in version control.

```bash
cp -n config/config.example.yaml config/config.yaml
cp -n config/secrets.example.yaml config/secrets.yaml
cp -n data/STC_set_data_sort.example.csv data/STC_set_data_sort.csv
chmod 600 config/secrets.yaml
```

| 本地文件 / Local file | 中文 | English |
| --- | --- | --- |
| `config/config.yaml` | 必需。预算、查询和下单间隔；[参数示例](config/config.example.yaml)。 | Required. Budgets and request delays; [settings example](config/config.example.yaml). |
| `config/secrets.yaml` | 必需。账号凭证；[凭证示例](config/secrets.example.yaml)。 | Required. Account credentials; [credentials example](config/secrets.example.yaml). |
| `data/STC_set_data_sort.csv` | 必需。待购买游戏清单；[表头示例](data/STC_set_data_sort.example.csv)。 | Required. Target game list; [CSV header example](data/STC_set_data_sort.example.csv). |

程序只读取上表中的实际文件名，不会自动读取或复制 `.example` 文件。进度、账号快照、日志和锁文件在运行时生成，无需手动创建。

The script reads only the actual filenames listed above; it does not load or copy `.example` files automatically. Progress, account snapshots, logs and the lock file are generated at runtime.

### 3. 填写购买清单 / Fill in the game list

在 `data/STC_set_data_sort.csv` 中填写真实游戏数据，以 UTF-8 保存，每行一个目标游戏。列名区分大小写；示例只有以下表头，没有可购买的游戏行。

Fill `data/STC_set_data_sort.csv` with real game data in UTF-8, one target game per row. Column names are case-sensitive. The example contains only this header, with no purchasable game rows.

自动购买只需要这一份输入清单。`data/progress.csv` 和 `data/user_info.json` 由程序生成，不需要复制示例或手工填写；`main.py` 不依赖其余数据文件。仓库仅提供字段结构，不附带真实游戏、价格或账号数据。

Auto-buying requires only this one input list. The script generates `data/progress.csv` and `data/user_info.json`; neither needs a template copy or manual entry. `main.py` does not depend on other data files. The repository provides only the column structure, with no real game, price or account data.

```csv
AppId,Game,# Cards,Set Price
```

| 列 / Column | 中文 | English |
| --- | --- | --- |
| `AppId` | 必填。游戏的 Steam App ID。 | Required. The game's Steam App ID. |
| `Game` | 必填。游戏名称，用于进度和日志。 | Required. Game name for progress and logs. |
| `# Cards` | 必填。一套普通卡牌的卡种数，填正整数。 | Required. Number of distinct cards in a regular set; use a positive integer. |
| `Set Price` | 可选。参考套价，首次运行时按数值从低到高排序。 | Optional. Reference set price, sorted numerically from low to high on the first run. |

也支持 `Set Price USD`，存在时优先使用。没有价格列时按文件顺序处理。参考价格只决定初始顺序，实际买价来自实时市场；清单需自行准备，程序不会自动下载。

`Set Price USD` is also supported and takes precedence when present. Without a price column, file order is used. Reference prices only set the initial order; buy prices come from the live market. Supply the list locally; the script does not download it.

<a id="configuration"></a>

## 配置 / Configuration

### 购买参数 / Purchase settings

编辑复制得到的 `config/config.yaml`。[参数示例](config/config.example.yaml)提供小额起始值，六项均需填写。金额单位为 **HKD 分**：`100 = HK$1.00`。预算和游戏数填正整数，查询尝试次数至少为 `1`，等待时间填非负秒数。

Edit the copied `config/config.yaml`. The [settings example](config/config.example.yaml) provides small-budget starting values; all six fields are required. Amounts are in **HKD cents**: `100 = HK$1.00`. Use positive integers for budgets and game count, at least `1` query attempt, and non-negative seconds for delays.

| 配置项 / Setting | 中文 | English |
| --- | --- | --- |
| `single_game_limit_hkd_cents` | 每增加一套徽章所需缺卡的成本上限。`500` 为每套 HK$5；一个游戏购买多套时可以超过 HK$5。 | Maximum missing-card cost for each additional badge set. `500` means HK$5 per set; buying several sets for one game can cost more. |
| `run_total_limit_hkd_cents` | 本次运行的预扫描预算。`2000` 为 HK$20；每次启动重新计数。 | Pre-scan budget for the current run. `2000` means HK$20; the counter resets on each launch. |
| `run_game_limit` | 本次运行最多为多少个游戏成功提交买单，不是扫描游戏数。 | Maximum number of games with successful order submissions in this run, not the number scanned. |
| `max_query_retries` | 查询最多尝试次数，包含首次请求；`3` 即首次加最多两次重试。不用于失败买单的自动重试。 | Maximum query attempts, including the first request; `3` allows up to two retries. Does not automatically retry failed buy orders. |
| `request_interval_seconds` | 部分查询、分页及重试之间的等待时间，不是所有 HTTP 请求的统一限速。 | Delay used between selected queries, pages and retries; not a global limit on every HTTP request. |
| `order_interval_seconds` | 每次下单尝试后的等待时间，成功或失败都会等待。 | Delay after each order attempt, whether it succeeds or fails. |

单个游戏的下单预算为「本次计划套数 × 每套上限」。运行总预算只在预扫描中检查，价格变化后未逐笔复核，**不能视为严格的总额封顶**。`grind_interval_seconds` 不由 `main.py` 读取，无需配置。

The per-game order budget is the planned number of sets multiplied by the per-set limit. The run budget is checked during pre-scan, not rechecked per order after prices change, so **it is not a strict total spending cap**. `main.py` does not read `grind_interval_seconds`; omit it.

### 账号凭证 / Credentials

编辑复制得到的 `config/secrets.yaml`，替换[凭证示例](config/secrets.example.yaml)中的占位符，保留引号。填写当前使用账号的凭证，不需要 Steam 登录密码。

Edit the copied `config/secrets.yaml`, replace the placeholders from the [credentials example](config/secrets.example.yaml), and keep the quotes. Use credentials from the account being used. The Steam login password is not required.

| 配置项 / Setting | 中文 | English |
| --- | --- | --- |
| `api_key` | 必填。Steam Web API Key，用于读取徽章。 | Required. Steam Web API key used to read badges. |
| `steamid` | 必填。17 位 SteamID64，以字符串填写。 | Required. The 17-digit SteamID64, entered as a string. |
| `steam_login_secure` | 必填。浏览器中的 `steamLoginSecure` Cookie 完整值。 | Required. Full value of the browser's `steamLoginSecure` cookie. |
| `sessionid` | 必填。同一登录会话的 `sessionid` Cookie。 | Required. The `sessionid` cookie from the same login session. |
| `steam_country_cookie` | 可选。`steamCountry` Cookie 完整值；省略时使用 `HK`。修改它不会切换程序的计价货币。 | Optional. Full `steamCountry` cookie value; defaults to `HK` if omitted. Changing it does not change the script's currency. |

登录 [Steam Web API Key](https://steamcommunity.com/dev/apikey) 页面查看或申请 API Key。登录 [Steam 社区市场](https://steamcommunity.com/market/) 后，在浏览器开发者工具的 **Application / Storage → Cookies → steamcommunity.com** 中读取上述 Cookie，完整复制，不手动解码。SteamID64 是账号的数字 ID，不是登录名。

View or request an API key on the [Steam Web API Key](https://steamcommunity.com/dev/apikey) page. After signing in to the [Steam Community Market](https://steamcommunity.com/market/), read the cookies under **Application / Storage → Cookies → steamcommunity.com** in browser developer tools. Copy their full values without manually decoding them. SteamID64 is the numeric account ID, not the login name.

Cookie 名为 `steamCountry`，但 YAML 中必须写作 `steam_country_cookie`。凭证只保存在本地；日志可能包含账号信息及请求细节，分享前需脱敏。

The cookie is named `steamCountry`, but its YAML key must be `steam_country_cookie`. Keep credentials local. Logs may include account information and request details; redact them before sharing.

<a id="run"></a>

## 运行 / Run

填写浏览器 Cookie 后，在项目目录中后台启动。启动脚本优先使用项目的 `.venv`，否则使用 `python3`；关闭终端后继续运行。

After filling in the browser cookies, start the process in the background from the project directory. The start script prefers the project's `.venv`, falling back to `python3`. The process keeps running after the terminal closes.

```bash
./start.sh
```

停止由启动脚本启动的进程：

Stop the process launched by the start script:

```bash
./stop.sh
```

重复启动会提示进程已在运行；停止脚本核对 PID 和当前项目路径。已提交到 Steam 的买单不会自动撤销，重启前先在市场页面核对未完成订单和库存。

Starting again reports the existing process. The stop script checks both the PID and the current project path. Orders already submitted to Steam are not cancelled automatically; check outstanding orders and inventory on the Market page before restarting.

在另一个终端查看日志：  
View logs in another terminal:

```bash
tail -f logs/console.log
```

`console.log` 汇总后台输出及启动错误；`run.log`、`business.log`、`error.log` 分别记录运行摘要、下单明细和错误。日志目录和本地 PID 目录由脚本创建。

`console.log` captures background output and startup errors. `run.log`, `business.log` and `error.log` contain run summaries, order details and errors respectively. The scripts create the log and local PID directories.

<a id="progress"></a>

## 进度与重跑 / Progress & reruns

首次运行生成 `data/progress.csv`，之后沿用该文件；不会把购买清单的新行自动合入已有进度。`data/user_info.json` 保存最近获取的徽章和库存快照。

The first run creates `data/progress.csv`; later runs reuse it. New rows in the game list are not automatically merged into existing progress. `data/user_info.json` stores the latest fetched badge and inventory snapshot.

| 情况 / Situation | 中文 | English |
| --- | --- | --- |
| `pending` / `in_progress` | 后续运行继续选择这些游戏；记录缺货扫描时间的游戏会冷却 3 天。 | Eligible for later runs; games with an out-of-stock scan timestamp have a 3-day cooldown. |
| `ready_to_craft` | 本次缺口已由库存或成功订单响应覆盖；到 Steam 核对成交和库存，再手动合成。 | The current shortage is covered by inventory or successful order responses. Verify fills and inventory in Steam before crafting manually. |
| `done` / `skipped` / `overpriced` | 不再自动选择。分别表示徽章已到 5 级、待处理游戏未搜到卡牌、首套缺卡成本超过单套上限两倍。 | Not selected automatically: badge level 5, no cards found for a pending game, or the first set's missing-card cost exceeds twice the per-set limit. |
| `Session expired` | 更新同一会话的 Cookie 后重跑。 | Refresh cookies from the same session, then rerun. |
| HTTP `429` | 表示限流；按日志等待或结束本轮，不要连续重启。 | Rate limited; follow the logged wait or exit, rather than restarting repeatedly. |

需要重新扫描已跳过的游戏时，停止程序，先核对 Steam 订单，再将对应进度行的 `status` 改为 `pending`。更换购买清单时，先备份并移走 `data/progress.csv`，下次运行会重新生成。

To rescan a skipped game, stop the script, check Steam orders, then set that progress row's `status` to `pending`. When replacing the game list, back up and move `data/progress.csv` aside; the next run recreates it.
