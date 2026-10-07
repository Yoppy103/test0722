"""キーワード辞書ベースの強気/弱気判定（日本語・英語）。

精度を上げたい場合は analyze() を LLM 判定などに差し替えられるよう、関数1つに閉じている。
"""
from __future__ import annotations

from .extractor import normalize

BULLISH = {
    # 日本語
    "買い": 1.0, "買い増し": 1.5, "仕込": 1.2, "爆上げ": 1.5, "上昇": 0.8, "上がる": 1.0, "上げ": 0.6,
    "反発": 0.8, "底打ち": 1.0, "ストップ高": 1.5, "s高": 1.5, "上方修正": 1.5, "増配": 1.2,
    "好決算": 1.5, "最高益": 1.3, "自社株買い": 1.2, "本命": 1.2, "期待": 0.7, "注目": 0.5,
    "ブレイク": 1.0, "高値更新": 1.0, "上抜け": 1.0, "ゴールデンクロス": 1.0, "割安": 0.8,
    "強い": 0.7, "握力": 0.6, "テンバガー": 1.2,
    "🚀": 1.0, "📈": 0.8,
    # 英語
    "buy": 1.0, "long": 0.8, "bullish": 1.2, "breakout": 1.0, "moon": 1.0, "calls": 0.8,
    "undervalued": 0.8, "upgrade": 1.0, "beat": 0.8,
}
BEARISH = {
    "売り": 1.0, "空売り": 1.5, "下落": 0.8, "暴落": 1.5, "下がる": 1.0, "下げ": 0.6, "急落": 1.2,
    "ストップ安": 1.5, "s安": 1.5, "下方修正": 1.5, "減配": 1.2, "無配": 1.2, "損切": 1.0,
    "天井": 1.0, "割高": 0.8, "弱い": 0.7, "デッドクロス": 1.0, "下抜け": 1.0, "利確": 0.5,
    "逃げ": 0.8, "撤退": 1.0, "悪材料": 1.2, "公募増資": 1.2, "希薄化": 1.0,
    "📉": 0.8,
    "sell": 1.0, "short": 1.0, "bearish": 1.2, "puts": 0.8, "dump": 1.2, "downgrade": 1.0, "miss": 0.8,
}
# 否定形（先に除去してから逆方向に加点）
NEGATED = {
    "上がらない": -1.0, "買わない": -1.0, "買えない": -0.5, "期待できない": -1.0, "強くない": -0.5,
    "下がらない": 1.0, "売らない": 0.7, "売られすぎ": 0.8, "下げ止まり": 0.8, "損切りしない": 0.3,
}


def analyze(text: str) -> float:
    """-1（弱気）〜+1（強気）。感情語がなければ 0。"""
    t = normalize(text).lower()
    bull = bear = 0.0
    for phrase, val in NEGATED.items():
        if phrase in t:
            if val > 0:
                bull += val
            else:
                bear += -val
            t = t.replace(phrase, " ")
    # 長い語から消費して二重計上を防ぐ（"買い増し" と "買い" など）
    for lex, sign in ((BULLISH, 1), (BEARISH, -1)):
        for word in sorted(lex, key=len, reverse=True):
            n = t.count(word)
            if n and lex[word]:
                if sign > 0:
                    bull += lex[word] * min(n, 2)
                else:
                    bear += lex[word] * min(n, 2)
                t = t.replace(word, " ")
    if bull == 0 and bear == 0:
        return 0.0
    return (bull - bear) / (bull + bear + 0.5)
