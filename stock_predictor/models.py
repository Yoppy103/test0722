from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class Author:
    id: str
    username: str
    followers: int
    verified: bool = False


@dataclass
class Post:
    id: str
    author: Author
    text: str
    created_at: datetime  # timezone-aware
    likes: int = 0
    retweets: int = 0
    replies: int = 0
    quotes: int = 0
    lang: Optional[str] = None


@dataclass
class TickerScore:
    ticker: str
    score: float  # 0-100
    social: float  # 0-1
    technical: float  # 0-1
    fundamental: float  # 0-1
    mentions: int
    unique_authors: int
    sentiment: float  # -1..1 (加重平均)
    detail: dict = field(default_factory=dict)
    rank: int = 0


@dataclass
class Trade:
    week: str
    ticker: str
    score: float
    entry_date: date
    entry_price: float
    shares: int
    exit_date: Optional[date] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    status: str = "open"  # open / closed
    hold_return_pct: Optional[float] = None  # 月曜寄り→金曜引けまで保有した場合のリターン（売却戦略の比較用）
    fees: float = 0.0

    @property
    def return_pct(self) -> Optional[float]:
        if self.exit_price is None:
            return None
        gross = (self.exit_price - self.entry_price) * self.shares
        return (gross - self.fees) / (self.entry_price * self.shares) * 100

    @property
    def pnl(self) -> Optional[float]:
        if self.exit_price is None:
            return None
        return (self.exit_price - self.entry_price) * self.shares - self.fees
