# 更新日志 / Changelog

## v1.0.0 — 2026-10-22

首个正式版本：美国经济数据预期差监控，全部运行在 GitHub Actions 上。
First stable release: a US economic data surprise monitor that runs entirely on GitHub Actions.

### 功能

- **7 个核心指标**：CPI、核心 CPI、核心 PCE、非农（含前值修正）、失业率、零售销售、初请失业金
- **标准化意外值**：意外 ÷ 历史意外标准差，统一换算为鹰 / 鸽方向；历史不足时使用保守估计
- **首次公布值**：意外按市场当时看到的数据计算，后续修正不改写历史
- **合成意外指数**：按美联储重视程度加权、30 天半衰期
- **历史同类事件统计**：同方向、同强度意外后，2 年美债、标普、纳指当天的平均表现
- **市场确认**：收盘后检查 2 年美债是否朝意外方向变动
- **多渠道推送**：微信（Server酱）、企业微信、Telegram、邮件；支持一键发送测试推送
- **可视化面板**：GitHub Pages 托管，支持深色模式和手机浏览
- **稳定性**：FRED 维护时自动重试，不误报失败；连续故障超过 3 小时推送提醒；同一事件只推送一次
- **安全**：所有密钥只存在 GitHub Secrets，报错信息不含密钥

### Features

- **7 core indicators**: CPI, core CPI, core PCE, nonfarm payrolls (with revisions), unemployment rate, retail sales, initial jobless claims
- **Standardized surprises**: surprise ÷ std. dev. of past surprises, mapped to a hawkish / dovish direction; conservative fallback when history is short
- **First-print accuracy**: surprises use the value the market saw on release day; later revisions never rewrite history
- **Composite surprise index**: weighted by Fed importance, 30-day half-life
- **Historical analogs**: average same-day move in the 2-year yield, S&P 500 and Nasdaq after similar surprises
- **Market confirmation**: checks after the close whether the 2-year yield moved with the surprise
- **Alerts**: WeChat (ServerChan), WeCom, Telegram, email; one-click test alert
- **Dashboard**: hosted on GitHub Pages, dark mode and mobile friendly
- **Reliability**: retries through FRED maintenance without false failures; alerts after 3+ hours of outage; each event alerted once
- **Security**: credentials live only in GitHub Secrets and never appear in error messages

### 开始使用 / Getting started

见 [README](https://github.com/Peacelover99/fed-watch#readme)（中文）或 [README.en.md](https://github.com/Peacelover99/fed-watch/blob/main/README.en.md)（English）。

> 仅供研究参考，不构成投资建议。For research purposes only. Not investment advice.
