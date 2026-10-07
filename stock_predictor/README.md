# X株予想ツール（stock_predictor）

X（旧Twitter）で株について発信している **フォロワー1万人以上** のアカウントの投稿を集め、
「来週上がりそうな銘柄」をスコア化してランキングにします。さらに **仮想取引（ペーパートレード）** で
「月曜寄付きで成行買い → 金曜までに売却」を自動で行い、予想の精度を検証します。

> ⚠ 研究・検証用のツールです。投資助言ではなく、利益を保証するものでもありません。

## 仕組み

```
 土日                     月曜 寄付き後          月〜金 引け後            金曜 引け後
 collect → score   →     buy（成行買い）   →    update（売却判定）  →   evaluate / report
 X投稿収集  ランキング      寄付き価格で約定        損切り/利確/シグナル      的中率・アカウント信頼度更新
```

### 1. 投稿収集（`sources/x_api.py`）
- X API v2 の recent search（直近7日）または指定アカウントのタイムラインから取得
- `public_metrics.followers_count` で **1万人未満を除外**
- リツイートは除外

### 2. スコアリング（`scorer.py`）  — 0〜100点
| 要素 | 既定の重み | 内容 |
|---|---|---|
| SNS | 50% | 銘柄ごとに「投稿者の影響力（フォロワー数の対数）× 過去の的中率 × エンゲージメント × 新しさ × 強気/弱気」を合算 |
| テクニカル | 30% | 25日線との位置、5日モメンタム（急騰しすぎは減点）、RSI（過熱は減点）、出来高増加、MACD |
| ファンダメンタル | 20% | PER・PBR・ROE・売上成長率。今週決算がある銘柄は10%減点（⚠決算表示） |

煽り・ノイズ対策:
- 同一アカウントの連投は逓減（最大でも1投稿の1.5倍まで）
- 銘柄を大量に並べた投稿は1銘柄あたりの重みを希釈
- 言及者が2人未満の銘柄は候補外
- **アカウント信頼度**: 毎週末、各アカウントの強気/弱気コールが当たったかを記録し、次週以降の重みに反映
  （的中率50%→×1.0、70%→×約2.0、30%→×約0.36）

銘柄抽出（`extractor.py`）は `【7203】` `(7203)` `7203.T` などのコード、`data/jp_tickers.csv` の銘柄名、
米国株の `$AAPL` に対応。「2026年」「1500円」「100株」などは除外します。
銘柄名辞書は JPX の上場銘柄一覧から `code,name` 形式（別名は `|` 区切り）で作ると網羅できます。

### 3. 仮想取引（`paper_trader.py` / `strategy.py`）
- **買い**: 週の最初の営業日の寄付き価格で成行（スリッページ込み）。上位 `top_n` 銘柄に資金を等分、単元株（100株）単位
- **売り**（日足で1日ずつ判定、先読みなし）
  | ルール | 内容 |
  |---|---|
  | 損切り | ATR×1.5（3〜8%の範囲）。窓を開けて下落したら寄付きで約定 |
  | 利確 | ATR×3（最低5%）の指値 |
  | トレーリングストップ | +4%到達後、高値から3%下落で売却 |
  | RSI過熱 | RSI(14) ≥ 78 |
  | モメンタム喪失 | 終値が5日EMAを下抜け |
  | 天井サイン | 含み益中に出来高2.5倍＋長い上ヒゲ |
  | 決算回避 | 決算発表の前営業日に手仕舞い |
  | 週末決済 | 金曜（週最終営業日）の引けで全決済 |
  - 引け後に出たシグナルの売りは既定で **翌営業日寄付き** に約定（`signal_execution = "close"` で当日引け）
  - 日足では高値と安値の順序が分からないため、同日に損切り・利確の両方に届いた場合は損切り扱い（保守的）

### 4. 検証レポート（`report.py`）
勝率、平均リターン、累積リターン、最大ドローダウン、ベンチマーク（日経平均）との比較、
**金曜まで単純保有した場合との比較（売却戦略が効いているか）**、
**スコアとリターンの順位相関（スコアが高い銘柄ほど本当に上がっているか）**、売却理由の内訳、アカウント別の的中率。

## セットアップ

```bash
pip install -r stock_predictor/requirements.txt
cp stock_predictor/config.example.toml stock_predictor/config.toml   # 必要に応じて編集
export X_BEARER_TOKEN=xxxxxxxx
```

X API について:
- 投稿の検索（`/2/tweets/search/recent`）は **Basic プラン以上（有料）** が必要です
- 検索のかわりに `config.toml` の `[x] accounts` に監視アカウントを列挙すると、そのアカウントのタイムラインだけを取得します（ノイズが少なく、API消費も少ない）
- X APIが使えない場合や過去データで検証したい場合は、JSONL ファイルから取り込めます（形式は `sources/file_source.py` 参照）

## 使い方

まずは擬似データで全体の動きを確認（ネット接続不要）:

```bash
python -m stock_predictor demo --weeks 12
```

本番運用（コマンドはリポジトリのルートで実行）:

```bash
python -m stock_predictor collect            # 土日: 直近7日の投稿を収集
python -m stock_predictor score              # 来週のランキングを表示・保存
python -m stock_predictor buy                # 月曜 寄付き後: 上位銘柄を仮想買い
python -m stock_predictor update             # 毎日 引け後: 売却判定
python -m stock_predictor evaluate           # 金曜 引け後: 結果確定・アカウント信頼度更新
python -m stock_predictor report             # 累積の検証レポート
python -m stock_predictor trades             # 取引一覧
python -m stock_predictor authors            # アカウント別の的中実績

# 過去データでのバックテスト（DBに該当期間の投稿が入っていること）
python -m stock_predictor collect --file past_posts.jsonl
python -m stock_predictor backtest --start 2026-07-06 --end 2026-09-28
```

cron 例（JST）:

```cron
0 10 * * 6   cd /path/to/repo && python -m stock_predictor collect && python -m stock_predictor score
5 9 * * 1-5  cd /path/to/repo && python -m stock_predictor buy      # 祝日明けの火曜なども拾える（買い済みは重複しない）
45 15 * * 1-5 cd /path/to/repo && python -m stock_predictor update
0 18 * * 5   cd /path/to/repo && python -m stock_predictor evaluate && python -m stock_predictor report
```

## 構成

```
stock_predictor/
  cli.py           コマンド
  pipeline.py      週次ワークフロー
  sources/x_api.py X API v2 クライアント（フォロワー数フィルタ）
  extractor.py     銘柄コード・銘柄名・$ティッカー抽出
  sentiment.py     強気/弱気判定（辞書ベース。LLMなどに差し替え可能）
  scorer.py        SNS×テクニカル×ファンダのスコアリング
  market_data.py   株価・ファンダ取得（yfinance / CSV / 擬似データ）
  strategy.py      売却ルール
  paper_trader.py  仮想売買
  report.py        検証レポート
  storage.py       SQLite（投稿・ランキング・取引・アカウント実績）
```

## 注意点・今後の改善案
- X上の推奨は、発信者が先に買ってから宣伝する「煽り」の可能性があります。アカウント信頼度で抑制しますが、十分な週数のデータが必要です
- 日足ベースの判定のため、実際のザラ場とは約定価格がずれます。より厳密にするなら分足データを使ってください
- 強気/弱気判定は辞書ベースです。皮肉や文脈は苦手なので、LLMによる判定に置き換えると精度向上が期待できます
- 十分な週数（最低でも数十週）検証してから判断してください。少ない週数の結果は偶然の影響が大きいです
