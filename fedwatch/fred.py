"""FRED 数据客户端。

有 FRED_API_KEY（免费申请：https://fred.stlouisfed.org/docs/api/api_key.html）时走官方 API，
还能拿到每期数据的「首次公布日期」；没有 key 时退回到无需认证的 CSV 下载，但没有公布日期。
"""
from __future__ import annotations

import io
import os
import time
from typing import Optional

import pandas as pd
import requests

API = "https://api.stlouisfed.org/fred"
CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredUnavailable(RuntimeError):
    """FRED 临时不可用（维护、5xx、返回空白/网页而不是数据、网络问题）。下一轮会自动重试。"""


class FredClient:
    def __init__(self, api_key: Optional[str] = None, session: Optional[requests.Session] = None):
        key = api_key if api_key is not None else os.environ.get("FRED_API_KEY", "")
        # 容错：去掉复制时常带进来的空格、换行、引号，以及 "api_key=" 前缀
        key = key.strip().strip("\"'").strip()
        if key.lower().startswith("api_key="):
            key = key[8:]
        self.api_key = key.lower() or None
        self.session = session or requests.Session()
        self._release_cache: dict[str, list[pd.Timestamp]] = {}

    def _get(self, url: str, params: dict, want_json: bool = False) -> requests.Response:
        last_err = ""
        transient = True
        endpoint = url.replace(API, "").replace(CSV, "fredgraph.csv")
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                # 网络错误信息里可能带完整 URL（含 api_key），只保留异常类型
                last_err = f"网络错误 {type(e).__name__}"
                time.sleep(1 + attempt)
                continue
            if r.status_code == 429:  # 限流，稍等再试
                last_err = "HTTP 429 限流"
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code >= 400:
                try:
                    msg = r.json().get("error_message", "")
                except ValueError:
                    msg = r.text[:200]
                last_err = f"HTTP {r.status_code} {msg}".strip()
                if r.status_code < 500:  # 4xx（如 key 无效）重试没用
                    transient = False
                    break
                time.sleep(1 + attempt)
                continue
            if want_json:
                # FRED 维护或故障时会返回 200 + 空白/网页，而不是 JSON
                try:
                    r.json()
                except ValueError:
                    ctype = r.headers.get("Content-Type", "?").split(";")[0]
                    last_err = f"返回的不是数据（{ctype}，{len(r.content)} 字节），FRED 可能在维护"
                    time.sleep(3 * (attempt + 1))
                    continue
            return r
        hint = "（请检查 FRED_API_KEY 是否正确：32 位小写字母和数字，不要带空格或引号）" \
            if "api_key" in last_err.lower() else ""
        cls = FredUnavailable if transient else RuntimeError
        raise cls(f"FRED {endpoint} {params.get('series_id', '')}: {last_err}{hint}")

    def series(self, series_id: str, start: str = "2000-01-01") -> pd.Series:
        """返回以观测日期为索引的 float 序列，缺失值已去掉。"""
        if self.api_key:
            r = self._get(
                f"{API}/series/observations",
                {"series_id": series_id, "api_key": self.api_key, "file_type": "json",
                 "observation_start": start},
                want_json=True,
            )
            obs = r.json()["observations"]
            s = pd.Series(
                [float(o["value"]) if o["value"] not in (".", "") else float("nan") for o in obs],
                index=pd.to_datetime([o["date"] for o in obs]),
                name=series_id,
            )
        else:
            r = self._get(CSV, {"id": series_id, "cosd": start})
            df = pd.read_csv(io.StringIO(r.text))
            date_col = df.columns[0]  # 'observation_date' 或旧版 'DATE'
            s = pd.Series(
                pd.to_numeric(df[series_id], errors="coerce").values,
                index=pd.to_datetime(df[date_col]),
                name=series_id,
            )
        return s.dropna().sort_index()

    def release_dates(self, series_id: str) -> list[pd.Timestamp]:
        """该序列所属发布（如 CPI 报告）的历次公布日期。没有 API key 时返回空列表。"""
        if not self.api_key:
            return []
        if series_id in self._release_cache:
            return self._release_cache[series_id]
        r = self._get(f"{API}/series/release",
                      {"series_id": series_id, "api_key": self.api_key, "file_type": "json"}, want_json=True)
        release_id = r.json()["releases"][0]["id"]
        r = self._get(
            f"{API}/release/dates",
            {"release_id": release_id, "api_key": self.api_key, "file_type": "json",
             "include_release_dates_with_no_data": "false", "sort_order": "asc", "limit": 10000},
            want_json=True,
        )
        dates = sorted(pd.Timestamp(d["date"]) for d in r.json()["release_dates"])
        self._release_cache[series_id] = dates
        return dates
