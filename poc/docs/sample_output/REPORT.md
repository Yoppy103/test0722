# スマレジ / Bカート API 技術検証（PoC）結果レポート

生成日時: 2026-09-07 00:28:58

> 本レポートは各検証スクリプトの実行結果を自動集計したもの。
> 結論・所見は docs/02_報告書テンプレート.md に転記して仕上げる。

## 1. 検証項目1: 外部APIから会員別価格（掛け率）を更新できるか

| ベンダ | 確認項目 | 結果 | 詳細 |
|---|---|---|---|
| smaregi | 認証 (client_credentials) | **OK** |  |
| smaregi | 商品一覧取得 | **OK** | 20件 |
| smaregi | 顧客グループ一覧 | **OK** | HTTP 200 |
| smaregi | 会員価格 priceDivision=2 の更新 | **OK** | HTTP 200 |
| smaregi | ★顧客グループ別 会員価格 | **OK** | customerGroupId が受理された → 会員別価格をスマレジ単体で実現可能 |
| smaregi | 一括価格更新API | **OK** | HTTP 200 |
| bcart | 認証 | **OK** |  |
| bcart | 商品一覧取得 | **OK** | 20件 |
| bcart | 会員一覧取得 | **OK** | 3件 |
| bcart | 価格グループ一覧 | **OK** | 3件 |
| bcart | ★価格グループの掛け率更新 | **OK** | HTTP 200 → グループ単位の掛け率を API から変更可能 |
| bcart | ★会員ID別 個別単価の更新 | **OK** | HTTP 200 |

## 2. 検証項目2: 更新1件あたりの所要時間

| 処理 | 件数 | 成功 | 失敗 | 最小(ms) | 平均(ms) | p50(ms) | p95(ms) | 最大(ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bcart:auth | 3 | 3 | 0 | 19.0 | 25.6 | 23.4 | 23.4 | 34.5 |
| bcart:create_customer | 3 | 3 | 0 | 22.2 | 30.1 | 31.9 | 31.9 | 36.3 |
| bcart:create_item | 20 | 20 | 0 | 17.6 | 27.4 | 27.6 | 36.0 | 39.1 |
| bcart:list_customers | 1 | 1 | 0 | 37.7 | 37.7 | 37.7 | 37.7 | 37.7 |
| bcart:list_items | 1 | 1 | 0 | 36.3 | 36.3 | 36.3 | 36.3 | 36.3 |
| bcart:list_stages | 2 | 2 | 0 | 39.0 | 39.1 | 39.0 | 39.0 | 39.1 |
| bcart:update_item_price | 61 | 61 | 0 | 17.4 | 29.7 | 31.8 | 40.5 | 41.0 |
| bcart:update_stage_rate | 5 | 5 | 0 | 27.9 | 29.4 | 28.4 | 30.6 | 32.3 |
| smaregi:auth | 3 | 3 | 0 | 34.1 | 37.9 | 35.7 | 35.7 | 43.9 |
| smaregi:create_customer | 3 | 3 | 0 | 28.2 | 35.6 | 37.3 | 37.3 | 41.4 |
| smaregi:create_product | 20 | 20 | 0 | 18.3 | 31.4 | 30.4 | 40.5 | 41.6 |
| smaregi:list_customer_groups | 1 | 1 | 0 | 20.9 | 20.9 | 20.9 | 20.9 | 20.9 |
| smaregi:list_products | 1 | 1 | 0 | 32.4 | 32.4 | 32.4 | 32.4 | 32.4 |
| smaregi:probe_bulk | 1 | 1 | 0 | 41.4 | 41.4 | 41.4 | 41.4 | 41.4 |
| smaregi:update_price | 62 | 62 | 0 | 17.2 | 30.5 | 31.2 | 40.3 | 41.7 |

**「1件」の定義（重要）**

| 経路 | 1件の意味 | 20商品×3会員に必要なコール数 |
|---|---|---:|
| スマレジ 会員価格更新 | 商品1点 × 会員1社 | 60 |
| Bカート 価格グループ掛け率 | 会員グループ1つ（全商品に波及） | 3 |
| Bカート 会員ID別 個別単価 | 商品1点 × 会員1社 | 60 |

> 所要時間は **API応答時間のみ**。レート制限による待機は含まない。
> Bカートは 300req/300秒 の制限があり、超過すると300秒ロックされる。実運用の実効スループットはこの制限が支配的になる。

## 3. 検証項目3: 会員ログイン画面への反映

| レイヤ | 確認件数 | 一致 | 不一致 |
|---|---:|---:|---:|
| API再取得での照合 | 123 | 123 | 0 |
| 会員ログイン画面での照合 | 60 | 60 | 0 |

**総合: 一致 183 / 183**


## 4. 生成物一覧

- `out/api_trace.jsonl` (114,981 bytes)
- `out/bcart_expected_prices.json` (28,787 bytes)
- `out/bcart_seed.json` (2,495 bytes)
- `out/bcart_seed_timings.csv` (2,652 bytes)
- `out/bcart_update_summary.md` (1,006 bytes)
- `out/bcart_update_timings.csv` (7,015 bytes)
- `out/probe_result.json` (1,549 bytes)
- `out/probe_result.md` (894 bytes)
- `out/probe_timings.csv` (1,427 bytes)
- `out/screen_cust001.html` (4,466 bytes)
- `out/screen_cust002.html` (4,468 bytes)
- `out/screen_cust003.html` (4,470 bytes)
- `out/smaregi_expected_prices.json` (12,616 bytes)
- `out/smaregi_seed.json` (2,310 bytes)
- `out/smaregi_seed_timings.csv` (3,067 bytes)
- `out/smaregi_update_summary.md` (943 bytes)
- `out/smaregi_update_timings.csv` (6,759 bytes)
- `out/verification_result.json` (32,379 bytes)
- `out/verification_result.md` (8,679 bytes)