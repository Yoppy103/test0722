"""ダミーデータ生成: 商品20点 / 会員3社。実データは一切使わない。"""
from __future__ import annotations

from dataclasses import dataclass

# 実在の企業名と紛れないよう、意図的に架空とわかる名前にする。
COMPANIES = [
    ("CUST001", "検証商事株式会社", 0.80),   # 掛け率 80%
    ("CUST002", "テスト物産株式会社", 0.75),  # 掛け率 75%
    ("CUST003", "サンプル流通株式会社", 0.70),  # 掛け率 70%
]

CATEGORIES = ["文具", "備品", "消耗品", "什器"]


@dataclass
class DummyProduct:
    code: str
    name: str
    list_price: int   # 定価（＝スマレジ priceDivision=1 / Bカート 通常価格）
    category: str


@dataclass
class DummyCustomer:
    code: str
    name: str
    rate: float       # 掛け率 (0.70 = 定価の70%)


def products(count: int = 20) -> list[DummyProduct]:
    out: list[DummyProduct] = []
    for i in range(1, count + 1):
        # 端数の出る定価にして、掛け率計算の丸め挙動を検証できるようにする。
        list_price = 980 + i * 137
        out.append(
            DummyProduct(
                code=f"POC{i:03d}",
                name=f"PoC検証商品{i:02d}",
                list_price=list_price,
                category=CATEGORIES[i % len(CATEGORIES)],
            )
        )
    return out


def customers() -> list[DummyCustomer]:
    return [DummyCustomer(code=c, name=n, rate=r) for c, n, r in COMPANIES]


def apply_rate(list_price: int, rate: float) -> int:
    """掛け率を適用した会員価格。丸めは円未満切り捨て。

    ※ 実運用では業種により切上/四捨五入が要件になる。PoC では切り捨てに固定し、
      「どの丸めでも同じ値が両システムに入るか」を検証の対象にする。
    """
    return int(list_price * rate)
