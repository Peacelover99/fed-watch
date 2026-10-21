# Fed Watch · 美国经济数据预期差监控

**中文** | [English](README.en.md)

[![Fed Watch](https://github.com/Peacelover99/fed-watch/actions/workflows/fedwatch.yml/badge.svg)](https://github.com/Peacelover99/fed-watch/actions/workflows/fedwatch.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

美联储看数据决策，市场早已把"预期中的数据"计入价格。**真正推动美债和美股的，是数据和预期之间的差距。**

Fed Watch 在每次美国关键经济数据公布后自动：

1. 从 FRED（圣路易斯联储）抓取最新数据和官方公布日期
2. 与市场一致预期对比，算出**标准化意外值（z）**，换算成**鹰 / 鸽方向**
3. 统计历史同类意外后，2 年美债、标普、纳指当天的平均反应
4. 推送到微信（Server酱）、企业微信、Telegram 或邮件
5. 收盘后检查 2 年美债是否朝意外方向变动（**市场确认 / 市场不买账**），再补一条推送
6. 更新可视化面板（GitHub Pages）

全部运行在 GitHub Actions 上，不需要服务器，个人使用完全免费。

**在线面板**：<https://peacelover99.github.io/fed-watch/> · [演示版（模拟数据）](https://peacelover99.github.io/fed-watch/demo.html)

> ⚠️ 仅供研究参考，不构成投资建议。

## 推送示例

```
🔴 核心CPI 环比 鹰派意外 +2.1σ

核心CPI 环比（2026-09）
实际 0.5%，预期 0.3%（来源：Investing.com）
意外 +0.2% = +2.10σ → 鹰派 z +2.10
历史同指标同类意外 8 次：2年美债平均 +9.5bp，标普 -1.12%（下跌概率 75%）
```

## 方法

```
意外         = 实际值 − 一致预期（非农另加前两月修正合计）
z            = 意外 ÷ 该指标历史意外的标准差
鹰派 z       = z × 方向（通胀/就业/零售高于预期为 +1；失业率/初请高于预期为 −1）
合成意外指数 = 各指标鹰派 z 的时间衰减加权平均（半衰期 30 天，按美联储重视程度加权）
```

- **为什么除以标准差**：核心 CPI 差 0.1% 和非农差 5 万人无法直接比较，标准化后统一成"几个标准差的意外"。默认 |z| ≥ 1.5 视为大意外。
- **历史不足时**：某指标的历史预期少于 6 期时，用"上期值当预测"的误差标准差代替。它通常比专业预期的误差大，算出的 z 偏小，属于保守估计，推送里会注明。
- **首次公布值**：意外按市场当时看到的首次公布值计算，之后的数据修正不会改写历史意外。
- **精度对齐**：比较前先四舍五入到公布精度，避免 0.349% vs 0.3% 这种伪意外。

默认监控的指标（可在 `config/indicators.yaml` 增删、调整权重）：

| 指标 | FRED 代码 | 权重 | 高于预期 |
|---|---|---|---|
| 核心 CPI 环比 | CPILFESL | 3 | 鹰 |
| CPI 环比 | CPIAUCSL | 2 | 鹰 |
| 核心 PCE 环比 | PCEPILFE | 3 | 鹰 |
| 非农新增就业（含前值修正） | PAYEMS | 3 | 鹰 |
| 失业率 | UNRATE | 2 | 鸽 |
| 零售销售环比 | RSAFS | 1 | 鹰 |
| 初请失业金人数 | ICSA | 1 | 鸽 |

## 快速开始（约 10 分钟）

### 1. Fork 本仓库

点右上角 **Fork**，然后在你的仓库里启用 Actions（**Actions** 页面点绿色按钮）。

### 2. 申请 FRED API Key（免费）

在 <https://fred.stlouisfed.org/docs/api/api_key.html> 注册申请，得到一串 32 位小写字母和数字。

### 3. 配置 Secrets

**Settings → Secrets and variables → Actions → New repository secret**：

| Secret | 说明 |
|---|---|
| `FRED_API_KEY` | 必填，上一步的 key |
| `SERVERCHAN_KEY` | [Server酱](https://sct.ftqq.com) 的 SendKey，推送到个人微信（最简单） |
| `WECOM_WEBHOOK` | 企业微信群机器人 webhook 地址 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Telegram 机器人 |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `ALERT_EMAIL_TO` | 邮件（如 QQ 邮箱：smtp.qq.com、465、授权码） |

推送渠道至少配一个，配几个就推几个。所有密钥只存在 Secrets 里，不会出现在代码、数据或日志中。

### 4. 开启 GitHub Pages

**Settings → Pages**：Source 选 *Deploy from a branch*，分支 `main`，目录 `/docs`。面板地址为 `https://<用户名>.github.io/<仓库名>/`。

### 5. 测试推送

**Actions → Fed Watch → Run workflow ▾**，勾选 **「只发送一条测试推送」** 后运行，微信会收到一条用最近真实数据生成的样例提醒。

> GitHub 手机 App 不显示这个勾选框，请用浏览器操作。

之后工作日美东 8:00–11:00（北京时间约 20:00–24:00）每 15 分钟自动检查一次，每天早上补抓前一日的收盘反应。

## 日常使用：录入预期

专业一致预期（彭博、路透）是付费数据，所以采用**手工录入**：数据公布前，在 `data/consensus.csv` 末尾加一行。可以直接在 GitHub 网页上编辑并提交，提交后会自动重算。

```csv
indicator,period,consensus,source,actual,revision,note
core_cpi,2026-10,0.3,Investing.com,,,
nfp,2026-10,120,Investing.com,,,
claims,2026-10-24,225,Investing.com,,,
```

| 指标 | `indicator` | `period` 写法 | `consensus` 单位 |
|---|---|---|---|
| CPI / 核心 CPI 环比 | `cpi` / `core_cpi` | 数据所属月份 `2026-10` | `0.3` = 0.3% |
| 核心 PCE 环比 | `core_pce` | `2026-09` | `0.2` = 0.2% |
| 非农新增就业 | `nfp` | `2026-10` | `100` = 10 万人 |
| 失业率 | `unrate` | `2026-10` | `4.2` = 4.2% |
| 零售销售环比 | `retail` | `2026-10` | `0.4` = 0.4% |
| 初请失业金 | `claims` | 统计周结束日（周六）`2026-10-24` | `225` = 22.5 万人 |

- `period` 是**数据所属期间**，不是公布日期。例如 11 月中旬公布的 CPI 是 10 月数据，写 `2026-10`。
- `actual` 和 `revision` 日常**留空**，系统自动抓取首次公布值、自动计算非农修正。只有补录历史时才需要填，因为 FRED 上的历史值已经被修正过。
- 预期值来源：Investing.com、ForexFactory、金十数据等财经日历的"预期"一栏。
- 数据公布了但没录预期时，会推送"未录入预期"提醒；补录后自动补算。

## 稳定性

- **FRED 维护或临时故障**：本轮记为警告并跳过，下一轮自动重试，数据不会丢；连续故障超过 3 小时推送一次提醒，恢复后再推送一次。
- **单个指标失败**不影响其他指标；只有配置错误（如 API Key 无效）导致全部失败时，Actions 才标红。
- 同一事件只推送一次，重复运行不会重复提醒。

## 本地运行

```bash
pip install -r requirements.txt
python -m fedwatch demo          # 模拟数据离线演示，生成 docs/demo.html（不需要网络）
export FRED_API_KEY=你的key
python -m fedwatch run --dry-run # 抓真实数据但不推送
python -m fedwatch backfill      # 按 consensus.csv 回填历史（不推送）
python -m fedwatch test-notify   # 测试推送渠道
python -m unittest discover -s tests
```

## 项目结构

```
config/indicators.yaml     指标、权重、阈值配置
data/consensus.csv         一致预期（手工维护）
data/events.csv            每次公布的计算结果（自动生成）
data/snapshots/            原始序列快照，用于计算前值修正
docs/                      面板（自动生成，GitHub Pages）
fedwatch/
  fred.py                  FRED 客户端
  surprise.py              预期差、标准差、合成指数、历史同类统计（纯计算）
  market.py                公布日市场反应
  pipeline.py              主流程与推送文案
  notify.py                推送渠道
  dashboard.py             面板生成
  demo.py                  模拟数据
```

## 已知局限

- **同日多条数据**：CPI 和零售同一天公布，或同日有美联储讲话时，市场反应无法完全归因到某一条数据。
- **日度数据**：用收盘价而非公布后 30 分钟的高频反应；FRED 的美债数据通常次日更新，所以"市场确认"会晚一天。
- **预期靠手录**：没录入预期的数据无法计算意外。

## 路线图

- 利率决议意外（FOMC 前后 2 年美债变动）
- 点阵图 vs 市场定价
- 美联储官员讲话鹰鸽打分
- 自动获取一致预期

## 许可证

[MIT](LICENSE)。数据来自 [FRED®](https://fred.stlouisfed.org)，使用须遵守 FRED 的[服务条款](https://fred.stlouisfed.org/legal/)。本项目与圣路易斯联储、美联储无任何关联。
