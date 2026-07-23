# ネタ探索システム改修計画 v3.1（2026-07-23確定）

3視点レビュー（戦略逆張り・技術実現性・設計）を経た確定版。このドキュメントが改修の正本。
経緯: 事業ノート `リサーチ（AIプロダクト）/README.md` の探索手法v3改訂（人力スイープ廃止・bot週次一本化・スキル前提撤去）を受けた実装計画。

## レビューで確定した事実（改修の根拠）

1. **ボトルネックは検証器（下流）**: #39カスハラキットは Google Ads 141クリック・CTR 9.55%・¥16,413 → CTAクリック2件（1.4%）→ フォーム送信0。壊れているのは「pass仮説→リード」の変換。信号収集の強化だけでは全passが同じ死に方をする
2. **App StoreレビューRSSは死亡**（2026年実機検証: feed.entryが空）。他社アプリレビューの無料機械取得は Google Play（google-play-scraperライブラリ）に切替
3. **使える公式ソース**: e-Gov法令API v2（無料・認証不要・商用可）、PR TIMES全体RSS（`https://prtimes.jp/index.rdf`、実データ確認済み）、YouTube Data API v3（無料1万unit/日、commentThreads≒1unit/100件）
4. **pass率KPIは廃止**（生成者と採点者が同一LLMでGoodhart化済み）。新KPI: **pass仮説あたりのリード獲得数** + reject理由の分布変化（診断用）
5. **状態管理の責務分割**: Issue=個別仮説の生きた記録（タイトルにスコアを埋めない・ラベルのみで状態表現）/ explored-map=カテゴリ判定のみ / pipeline-learnings.md=手法論のみ

## フェーズ構成

### Phase 0（最優先・時間制約あり）: 検証器の修理
- #39敗因分析 → LP改修 → 日額¥500再テスト → それでもリード0なら仮説棚上げ
- **施行日2026-10-01の3-4ヶ月前窓は8月が最後。再テストは8月中に実施**
- 広告再開は費用が発生するためユーザー判断。LP改修まではbot側で実施
- 敗因分析: `docs/kasuhara-postmortem.md`

### Phase 1: explored-map（再発見ループ停止）
- `bot/data/explored-map.json` 新設。pipeline-learnings.md の「避けるべき領域」を移行し、learnings側の一覧は削除（二重管理禁止）
- スキーマ（設計レビュー反映）:

```json
{
  "version": 1,
  "entries": [
    {
      "category_path": ["建設業", "一人親方", "安全衛生証跡"],
      "keywords": ["安衛法", "一人親方", "証跡"],
      "verdict": "avoid | recheck | open",
      "verdict_date": "2026-07-03",
      "evidence": "判定根拠の要約",
      "evidence_url": "https://...",
      "recheck_date": "2027-01-15",
      "related_issue": 48
    }
  ]
}
```

- マッチング規則: 祖先ノードのavoidは子に継承。子側に明示エントリ（recheck/open）があれば優先。キーは厳密ルックアップではなく、LLMが category_path + keywords を見て判断する参考データ
- `bot/explored_map.py`: `due_rechecks()`（recheck_date<=today のみ返す）と `add_entry()` を提供

### Phase 2: 収集bot4本（非LLM・GitHub Actions cron）

| コレクタ | ソース | 頻度 | 備考 |
|---|---|---|---|
| laws | e-Gov法令API v2（更新法令一覧） | 週次 | 施行3-4ヶ月前窓の検知。官報は代替不可のため使わない |
| prtimes | PR TIMES全体RSS | 日次 | キーワード: サービス終了/価格改定/値上げ/事業譲渡/吸収合併/提供終了/サポート終了 等の供給側イベント。内部利用のみ・再配布禁止（規約グレーの注意） |
| gplay | Google Play レビュー（google-play-scraper） | 日次 | `bot/data/monitored-apps.json` の★1-2のみ。規約グレー・内部利用のみ |
| youtube | YouTube Data API v3 commentThreads | 日次 | `monitored-videos.json` の動画コメントをニーズ語フィルタで粗選別。search.listは高コスト(100unit)のため定点監視中心。APIキーはActionsシークレット `YOUTUBE_API_KEY` |

**signals共通スキーマ**（`bot/data/signals/{source}-{YYYY-MM}.jsonl`、追記専用）:

```json
{"id": "sha1(source+native_id)", "source": "gplay|youtube|prtimes|laws", "collected_at": "ISO8601", "native_id": "...", "raw_category": "機械的に取れる粗い分類のみ（意味分類はLLM層の仕事）", "title": "...", "body": "...", "url": "...", "meta": {}}
```

- 処理状態は `bot/data/signals/processed_ids.json`（処理済みidの配列）で別管理。jsonl本体はimmutable
- 死活監視: 各コレクタ成功時に `bot/data/signals/_health.json` へ `{source: {last_success_at, rows_collected}}` を記録。週次パイプラインStep 0で7日超の停止を警告
- Actions対策: cron分は0分を避ける / 60日無コミット停止対策に月次keepaliveワークフロー / パブリックリポなので無料枠無制限
- アーカイブ: 処理済み90日超の行は月次で集計サマリに置換（肥大化対策）
- validate.py に1回のpostでのIssue作成上限（5件）を追加

### Phase 3: SKILL改修（weekly-pipeline）
- Step 1「WebSearch×9ソース」→「signals未処理分の読み込み」に置換。WebSearchは①スキャンと深掘り専用
- Step 0 に _health.json チェックと explored-map の期限切れrecheckキューを追加
- 探索対象の重心: 横断SaaSカテゴリ → **業界バーティカル×規制イベント×供給側イベント**
- 海外ネタの採用条件: 日本固有の規制・商慣習の翻訳障壁があるもの限定。単純移植は自動reject
- monitored-apps/videos の追加・削除はLLMセッションが週次で行う（cronは受動的にリストを読むだけ）
- ソース剪定: 候補が累計10件以上溜まったソースのみ寄与率を評価（早すぎる剪定の禁止）

## 評価チェックポイント

- **2026-08-20頃（収集bot稼働4週間後）**: (1) reject理由の分布が「飽和」一辺倒から変わったか (2) #39再テストのリード数 (3) ソース別の候補供給数 — で改修の成否を判定
- 変わっていなければボトルネックは審査関数か探索空間にあると確定し、次の一手を再設計する

## 採用しなかったレビュー指摘（記録）

- 「医療・介護の手持ちドメイン資産の活用（#14再開）」: 2026-07-23のユーザー決定（スキル前提の完全撤去）と矛盾するため不採用。レビュー側の論拠は「他人に見えない信号は資産からしか出ない」。再検討する場合はユーザー判断で
