# API 能力調査結果

| ベンダ | 確認項目 | 結果 | 詳細 |
|---|---|---|---|
| smaregi | 認証 (client_credentials) | OK |  |
| smaregi | 商品一覧取得 | OK | 20件 |
| smaregi | 顧客グループ一覧 | OK | HTTP 200 |
| smaregi | 会員価格 priceDivision=2 の更新 | OK | HTTP 200 |
| smaregi | ★顧客グループ別 会員価格 | OK | customerGroupId が受理された → 会員別価格をスマレジ単体で実現可能 |
| smaregi | 一括価格更新API | OK | HTTP 200 |
| bcart | 認証 | OK |  |
| bcart | 商品一覧取得 | OK | 20件 |
| bcart | 会員一覧取得 | OK | 3件 |
| bcart | 価格グループ一覧 | OK | 3件 |
| bcart | ★価格グループの掛け率更新 | OK | HTTP 200 → グループ単位の掛け率を API から変更可能 |
| bcart | ★会員ID別 個別単価の更新 | OK | HTTP 200 |

NG: 0 件 / 全 12 件
