"""投稿本文から銘柄コード/ティッカーを抽出する。"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# 米国株: $AAPL, $BRK.B
CASHTAG = re.compile(r"(?<![A-Za-z0-9])\$([A-Za-z]{1,5}(?:\.[A-Za-z])?)(?![A-Za-z0-9])")
# 日本株: 4桁コード（新形式の英字入り 130A なども）
JP_CODE = re.compile(r"(?<![0-9A-Za-z¥$.,+\-])([1-9][0-9]{2}[0-9A-Z])(\.T)?(?![0-9A-Za-z])")
# コードとして強い文脈（【7203】(7203) #7203 7203.T）
STRONG_BEFORE = "【[(#「"
STRONG_AFTER = "】])」"
# 直後に来たら数量・日付・金額とみなして除外する文字
NOT_CODE_AFTER = set("年月日円%％株倍万億千件人回時分秒歳位枚口本台個社")

# 米国株で誤検出しやすい（$記号付きでも通貨や一般語の）トークン
US_STOPWORDS = {"USD", "JPY", "EUR", "BTC", "ETH", "CEO", "IPO", "ETF", "GDP", "CPI", "FOMC"}


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def load_jp_names(path: Path | None = None) -> dict[str, str]:
    """銘柄名→コード辞書。CSV（code,name）。JPXの上場銘柄一覧から作ると網羅できる。"""
    path = path or DATA_DIR / "jp_tickers.csv"
    names: dict[str, str] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fp:
            for row in csv.DictReader(fp):
                code = row["code"].strip()
                for name in row["name"].split("|"):
                    name = normalize(name.strip())
                    if len(name) >= 2:
                        names[name] = code
    return names


class TickerExtractor:
    def __init__(self, market: str = "jp", jp_names: dict[str, str] | None = None,
                 jp_universe: set[str] | None = None):
        self.market = market
        self.jp_names = jp_names if jp_names is not None else load_jp_names()
        # 既知コード集合（辞書から）。これに含まれるコードは文脈がなくても採用
        self.jp_universe = jp_universe if jp_universe is not None else set(self.jp_names.values())
        # 長い名前を優先してマッチ
        self._names_sorted = sorted(self.jp_names, key=len, reverse=True)

    def extract(self, text: str) -> list[str]:
        text = normalize(text)
        found: list[str] = []
        if self.market in ("us", "both"):
            for m in CASHTAG.finditer(text):
                sym = m.group(1).upper()
                if sym not in US_STOPWORDS:
                    found.append(sym)
        if self.market in ("jp", "both"):
            found.extend(self._extract_jp(text))
        # 順序を保って重複除去
        return list(dict.fromkeys(found))

    def _extract_jp(self, text: str) -> list[str]:
        out = []
        for m in JP_CODE.finditer(text):
            code = m.group(1)
            start, end = m.span()
            after = text[end:end + 1]
            before = text[start - 1:start] if start > 0 else ""
            if after in NOT_CODE_AFTER:
                continue
            strong = bool(m.group(2)) or (before and before in STRONG_BEFORE) or (after and after in STRONG_AFTER)
            # 直後に銘柄名が続く形（"7203 トヨタ"）も強い文脈とする
            tail = text[end:end + 12].strip()
            named = any(tail.startswith(n) for n, c in self.jp_names.items() if c == code)
            if strong or named or code in self.jp_universe:
                out.append(f"{code}.T")
        masked = text
        for name in self._names_sorted:
            if name in masked:
                out.append(f"{self.jp_names[name]}.T")
                masked = masked.replace(name, " ")
        return out
