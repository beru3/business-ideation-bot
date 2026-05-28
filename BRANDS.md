# brands.json ドキュメント

## 概要

`brands.json` はハブ&スポーク戦略の定義ファイル。各アイデアがどのスポーク事業に紐づくかを自動判定するために使用。

## 構造

### hub

バーバラ企画（親ブランド）の情報。

### spokes

各スポーク事業の定義。

| フィールド | 型 | 説明 |
|---|---|---|
| `id` | string | 一意ID（`spoke_` プレフィックス） |
| `name` | string | 表示名 |
| `status` | enum | `candidate` / `active_testing` / `active` / `paused` / `archived` |
| `target_domains` | string[] | themes.json の domain ID |
| `target_keywords` | string[] | テーマ文字列とのキーワードマッチに使用 |
| `lp_url` | string? | LP URL（あれば） |
| `twitter` | string? | 専用Xアカウント（あれば） |
| `started_at` | string? | 開始日（ISO 8601） |

## スポーク自動判定ロジック

1. 生成されたテーマ文字列に各スポークの `target_keywords` が含まれるか照合
2. 一致数が最も多いスポークを割当
3. 一致なしの場合 `unassigned`

## スポーク追加手順

1. `brands.json` の `spokes` 配列に新エントリを追加
2. `target_keywords` に関連キーワードを設定
3. コミット＆プッシュ（CLIは現時点では未実装）
