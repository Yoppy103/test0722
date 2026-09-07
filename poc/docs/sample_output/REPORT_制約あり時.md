# スマレジ / Bカート API 技術検証（PoC）結果レポート

生成日時: 2026-09-07 00:31:37

> 本レポートは各検証スクリプトの実行結果を自動集計したもの。
> 結論・所見は docs/02_報告書テンプレート.md に転記して仕上げる。

## 1. 検証項目1: 外部APIから会員別価格（掛け率）を更新できるか

| ベンダ | 確認項目 | 結果 | 詳細 |
|---|---|---|---|
| smaregi | 認証 (client_credentials) | **OK** |  |
| smaregi | 商品一覧取得 | **OK** | 20件 |
| smaregi | 顧客グループ一覧 | **OK** | HTTP 200 |
| smaregi | 会員価格 priceDivision=2 の更新 | **OK** | HTTP 200 |
| smaregi | ★顧客グループ別 会員価格 | **NG** | HTTP 400 — スマレジ単体では会員別価格を持てない可能性。Bカート側で会員別価格を持つ構成を検討（docs/01_API調査メモ.md 参照） |
| smaregi | 一括価格更新API | **NG** | HTTP 404 — 存在しなければ1件ずつ更新にフォールバック |
| bcart | 認証 | **OK** |  |
| bcart | 商品一覧取得 | **OK** | 20件 |
| bcart | 会員一覧取得 | **OK** | 3件 |
| bcart | 価格グループ一覧 | **OK** | 3件 |
| bcart | ★価格グループの掛け率更新 | **OK** | HTTP 200 → グループ単位の掛け率を API から変更可能 |
| bcart | ★会員ID別 個別単価の更新 | **OK** | HTTP 200 |

## 2. 検証項目2: 更新1件あたりの所要時間

| 処理 | 件数 | 成功 | 失敗 | 最小(ms) | 平均(ms) | p50(ms) | p95(ms) | 最大(ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bcart:auth | 3 | 3 | 0 | 16.3 | 21.2 | 22.2 | 22.2 | 25.0 |
| bcart:create_customer | 3 | 3 | 0 | 13.8 | 15.2 | 14.1 | 14.1 | 17.7 |
| bcart:create_item | 20 | 20 | 0 | 12.1 | 19.6 | 20.1 | 25.1 | 26.1 |
| bcart:list_customers | 1 | 1 | 0 | 22.2 | 22.2 | 22.2 | 22.2 | 22.2 |
| bcart:list_items | 1 | 1 | 0 | 15.8 | 15.8 | 15.8 | 15.8 | 15.8 |
| bcart:list_stages | 2 | 2 | 0 | 11.6 | 17.3 | 11.6 | 11.6 | 22.9 |
| bcart:update_item_price | 61 | 61 | 0 | 11.8 | 19.8 | 20.1 | 26.0 | 26.5 |
| bcart:update_stage_rate | 5 | 5 | 0 | 18.7 | 23.3 | 24.8 | 25.8 | 26.4 |
| smaregi:auth | 3 | 3 | 0 | 13.7 | 18.1 | 15.6 | 15.6 | 24.9 |
| smaregi:create_customer | 3 | 3 | 0 | 15.7 | 19.5 | 17.7 | 17.7 | 25.0 |
| smaregi:create_product | 20 | 20 | 0 | 11.9 | 19.4 | 19.6 | 24.8 | 25.1 |
| smaregi:list_customer_groups | 1 | 1 | 0 | 11.4 | 11.4 | 11.4 | 11.4 | 11.4 |
| smaregi:list_products | 1 | 1 | 0 | 16.8 | 16.8 | 16.8 | 16.8 | 16.8 |
| smaregi:probe_bulk | 1 | 0 | 1 | - | - | - | - | - |
| smaregi:update_price | 7 | 1 | 6 | 13.4 | 13.4 | 13.4 | 13.4 | 13.4 |

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
| API再取得での照合 | 68 | 63 | 5 |
| 会員ログイン画面での照合 | 60 | 60 | 0 |

**総合: 一致 123 / 128**

### 不一致の明細

- api / CUST001 / POC001: 期待=893 実際=1000 
- api / CUST001 / POC002: 期待=1003 実際=None 
- api / CUST001 / POC003: 期待=1112 実際=None 
- api / CUST001 / POC004: 期待=1222 実際=None 
- api / CUST001 / POC005: 期待=1332 実際=None 


## 4. 生成物一覧

- `out/api_trace.jsonl` (74,437 bytes)
- `out/bcart_expected_prices.json` (28,787 bytes)
- `out/bcart_seed.json` (2,495 bytes)
- `out/bcart_seed_timings.csv` (2,659 bytes)
- `out/bcart_update_summary.md` (1,006 bytes)
- `out/bcart_update_timings.csv` (7,037 bytes)
- `out/probe_result.json` (1,698 bytes)
- `out/probe_result.md` (1,043 bytes)
- `out/probe_timings.csv` (1,557 bytes)
- `out/screen_cust001.html` (4,466 bytes)
- `out/screen_cust002.html` (4,468 bytes)
- `out/screen_cust003.html` (4,470 bytes)
- `out/smaregi_expected_prices.json` (1,056 bytes)
- `out/smaregi_seed.json` (2,310 bytes)
- `out/smaregi_seed_timings.csv` (3,069 bytes)
- `out/smaregi_update_summary.md` (1,708 bytes)
- `out/smaregi_update_timings.csv` (1,156 bytes)
- `out/verification_result.json` (22,825 bytes)
- `out/verification_result.md` (6,160 bytes)