# Fed Watch · 美国经济数据预期差监控

美联储的政策取决于数据，而市场早已把"预期中的数据"计入价格。**真正推动美债和美股的，是数据和预期之间的差距。**
这个项目在每次美国关键经济数据公布后自动：

1. 从 FRED（圣路易斯联储）抓取最新数据
2. 和你录入的市场一致预期对比，算出**标准化意外值（z）**，并换算成**鹰 / 鸽方向**
3. 用历史同类意外统计当天 2 年美债、标普、纳指的平均反应
4. 推送到微信 / 企业微信 / Telegram / 邮件
5. 收盘后检查 2 年美债是否朝意外方向变动（**市场确认 / 市场不买账**），再补一条推送
6. 更新可视化面板（GitHub Pages）

全部跑在 GitHub Actions 上，不需要自己的服务器。

> 仅供研究参考，不构成投资建议。

## 核心计算

```
意外        = 实际值 − 一致预期（非农另加前两月修正合计）
z           = 意外 ÷ 该指标历史意外的标准差
鹰派 z      = z × 方向（通胀/就业/零售高于预期为 +1；失业率/初请高于预期为 −1）
合成意外指数 = 各指标鹰派 z 的时间衰减加权平均（半衰期 30 天，按美联储重视程度加权）
```

- **为什么要除以标准差**：核心 CPI 差 0.1% 和非农差 5 万人没法直接比较，标准化后都变成"几个标准差的意外"。
- **历史不够时**：录入的预期少于 6 期时，用"上期值当预测"的误差标准差代替。它通常比专业预期的误差大，算出的 z 偏小，属于保守估计，推送里会注明。
- **比较前先四舍五入到公布精度**，避免 0.349% vs 0.3% 这种伪意外。

默认监控的指标（可在 `config/indicators.yaml` 增删、调整权重）：

| 指标 | FRED | 权重 | 高于预期 |
|---|---|---|---|
| 核心 CPI 环比 | CPILFESL | 3 | 鹰 |
| CPI 环比 | CPIAUCSL | 2 | 鹰 |
| 核心 PCE 环比 | PCEPILFE | 3 | 鹰 |
| 非农新增就业（含修正） | PAYEMS | 3 | 鹰 |
| 失业率 | UNRATE | 2 | 鸽 |
| 零售销售环比 | RSAFS | 1 | 鹰 |
| 初请失业金 | ICSA | 1 | 鸽 |

## 部署（约 10 分钟）

### 1. 申请 FRED API Key（免费，强烈建议）
到 <https://fred.stlouisfed.org/docs/api/api_key.html> 注册申请。有 key 才能拿到每期数据的**官方公布日期**，历史回填和市场反应统计都依赖它。

### 2. 配置 GitHub Secrets
仓库 **Settings → Secrets and variables → Actions → New repository secret**，按需添加：

| Secret | 说明 |
|---|---|
| `FRED_API_KEY` | 上一步申请的 key |
| `SERVERCHAN_KEY` | [Server酱](https://sct.ftqq.com) 的 SendKey，推送到个人微信，最简单 |
| `WECOM_WEBHOOK` | 企业微信群机器人 webhook 地址 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram 机器人 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `ALERT_EMAIL_TO` | 邮件（如 QQ 邮箱 smtp.qq.com、465 端口、授权码） |

推送渠道配一个就够，配几个就推几个。

### 3. 开启 GitHub Pages（面板）
**Settings → Pages → Build and deployment**：Source 选 *Deploy from a branch*，分支选 `main`，目录选 `/docs`。
面板地址为 `https://<你的用户名>.github.io/<仓库名>/`，模拟数据的演示版在 `.../demo.html`。

> 私有仓库开 Pages 需要付费计划；不开 Pages 也可以直接下载 `docs/index.html` 用浏览器打开。

### 4. 运行
**Actions → Fed Watch → Run workflow** 手动跑一次。之后工作日北京时间约 20:00~24:00（美东 8:00~11:00）每 15 分钟自动检查，每天早上补一次收盘反应。

## 日常使用：录入预期

预期值是整个系统的关键输入。专业一致预期（彭博、路透）是付费的，所以这一版采用**手工录入**：数据公布前，在 `data/consensus.csv` 加一行。

```csv
indicator,period,consensus,source,note
core_cpi,2026-10,0.3,Investing.com,
nfp,2026-10,120,Investing.com,
claims,2026-10-24,225,Investing.com,周度填该周结束的周六
```

- 可以直接在 GitHub 网页上编辑这个文件并提交，会自动触发一次重算。
- 免费的预期值来源：Investing.com / ForexFactory 财经日历、新浪财经·金十数据的日历、各大券商研报。
- 数据公布了但没录预期时，会推送一条"未录入预期"提醒，补录后会自动补算并推送。

### 积累历史（让"同类事件统计"有意义）

历史统计需要足够多的"历史预期"。如果你能找到过去的预期值，一次性批量录入 `consensus.csv`，然后在本地运行：

```bash
pip install -r requirements.txt
export FRED_API_KEY=你的key
python -m fedwatch backfill --periods 120
```

回填不会推送，只会计算并写入 `data/events.csv`。

## 本地命令

```bash
python -m fedwatch demo          # 模拟数据离线演示，生成 docs/demo.html（不需要网络）
python -m fedwatch run --dry-run # 抓真实数据但不推送
python -m fedwatch test-notify   # 测试推送渠道
python -m fedwatch dashboard     # 只重新生成面板
python -m unittest discover -s tests
```

## 推送示例

```
🔴 核心CPI 环比 鹰派意外 +2.1σ

核心CPI 环比（2026-09）
实际 0.5%，预期 0.3%（来源：Investing.com）
意外 +0.2% = +2.10σ → 鹰派 z +2.10
历史同指标同类意外 8 次：2年美债平均 +9.5bp，标普 -1.12%（下跌概率 75%）
```

## 项目结构

```
config/indicators.yaml     指标、权重、阈值配置
data/consensus.csv         手工录入的一致预期（你维护）
data/events.csv            每次公布的计算结果（自动生成）
data/snapshots/            原始序列快照，用于计算前值修正
docs/index.html            面板（自动生成）
fedwatch/
  fred.py                  FRED 客户端
  surprise.py              预期差、标准差、合成指数、历史同类统计（纯计算）
  market.py                公布日市场反应
  pipeline.py              主流程与推送文案
  notify.py                推送渠道
  dashboard.py             面板生成
  demo.py                  模拟数据
```

## 已知局限 & 下一步

- **公布日混杂**：CPI 和零售同一天公布、或同日有美联储讲话时，市场反应无法完全归因到某一条数据。
- **日度数据**：用的是收盘价，不是公布后 30 分钟的高频反应；FRED 的美债数据通常次日才更新。
- **预期靠手录**：后续可接入 Trading Economics 等付费 API 自动获取。
- 下一步计划：利率决议意外（FOMC 前后 2 年美债）、点阵图 vs 市场定价、美联储讲话鹰鸽打分。
