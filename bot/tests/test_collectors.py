"""信号収集bot (Phase 2) のネットワーク不要ロジックのテスト。

実行: python -m pytest bot/tests/test_collectors.py
"""
from __future__ import annotations

import hashlib
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collectors"))

import common  # noqa: E402
import gplay  # noqa: E402
import laws  # noqa: E402
import prtimes  # noqa: E402
import youtube  # noqa: E402


# ──────────────────────────────────────────────
# common: id生成
# ──────────────────────────────────────────────
class TestMakeId:
    def test_sha1_of_source_plus_native_id(self):
        # 仕様: sha1(source + native_id) の連結
        assert common.make_id("prtimes", "x") == hashlib.sha1(b"prtimesx").hexdigest()

    def test_deterministic(self):
        assert common.make_id("laws", "abc") == common.make_id("laws", "abc")

    def test_differs_by_source(self):
        assert common.make_id("gplay", "abc") != common.make_id("youtube", "abc")


class TestBuildSignal:
    def test_schema_fields(self):
        sig = common.build_signal(
            source="prtimes", native_id="n1", title="t", body="b",
            url="https://example.com", raw_category="c", meta={"k": 1},
        )
        assert set(sig.keys()) == {
            "id", "source", "collected_at", "native_id",
            "raw_category", "title", "body", "url", "meta",
        }
        assert sig["id"] == common.make_id("prtimes", "n1")
        assert sig["meta"] == {"k": 1}

    def test_rejects_unknown_source(self):
        with pytest.raises(ValueError):
            common.build_signal(source="rss", native_id="n", title="", body="", url="")

    def test_rejects_empty_native_id(self):
        with pytest.raises(ValueError):
            common.build_signal(source="laws", native_id="", title="", body="", url="")


# ──────────────────────────────────────────────
# common: 重複排除 (当月+前月照合) / 追記 / 死活記録
# ──────────────────────────────────────────────
class TestAppendSignals:
    def _sig(self, native_id: str) -> dict:
        return common.build_signal(
            source="prtimes", native_id=native_id, title="t", body="b", url="u",
        )

    def test_append_then_dedupe_same_run(self, tmp_path):
        sig = self._sig("a1")
        assert common.append_signals("prtimes", [sig, sig], signals_dir=tmp_path) == 1

    def test_dedupe_against_current_month_file(self, tmp_path):
        sig = self._sig("a1")
        assert common.append_signals("prtimes", [sig], signals_dir=tmp_path) == 1
        # 再実行 (冪等性): 同じ信号は書き込まれない
        assert common.append_signals("prtimes", [sig], signals_dir=tmp_path) == 0
        assert common.append_signals("prtimes", [sig, self._sig("a2")], signals_dir=tmp_path) == 1

    def test_dedupe_against_previous_month_file(self, tmp_path):
        sig = self._sig("a1")
        _, prev_month = common.month_keys()
        prev_file = tmp_path / f"prtimes-{prev_month}.jsonl"
        import json as _json
        prev_file.write_text(_json.dumps(sig, ensure_ascii=False) + "\n", encoding="utf-8")

        assert common.append_signals("prtimes", [sig], signals_dir=tmp_path) == 0

    def test_health_recorded(self, tmp_path):
        common.record_health("prtimes", 3, signals_dir=tmp_path)
        common.record_health("laws", 7, signals_dir=tmp_path)
        import json as _json
        health = _json.loads((tmp_path / "_health.json").read_text(encoding="utf-8"))
        assert health["prtimes"]["rows_collected"] == 3
        assert health["laws"]["rows_collected"] == 7
        assert "last_success_at" in health["prtimes"]


class TestMonthKeys:
    def test_january_previous_is_december(self):
        assert common.month_keys(date(2026, 1, 15)) == ("2026-01", "2025-12")

    def test_normal_month(self):
        assert common.month_keys(date(2026, 7, 23)) == ("2026-07", "2026-06")


# ──────────────────────────────────────────────
# prtimes: キーワードマッチ
# ──────────────────────────────────────────────
class TestPrtimesKeywords:
    @pytest.mark.parametrize("title,expected", [
        ("「フォトブックアプリA」サービス終了のお知らせ", ["サービス終了"]),
        ("2026年10月より価格改定を実施いたします", ["価格改定"]),
        ("原材料高騰に伴う値上げについて", ["値上げ"]),
        ("株式会社Bの事業譲渡に関するお知らせ", ["事業譲渡"]),
        ("○○ソフトのサポート終了と提供終了について", ["提供終了", "サポート終了"]),
        # 2026-07拡張キーワード
        ("○○事業からの撤退に関するお知らせ", ["撤退"]),
        ("ロングセラー商品「△△」終売のご案内", ["終売"]),
        ("××シリーズ販売終了のお知らせ", ["販売終了"]),
        ("子会社2社の経営統合について", ["経営統合"]),
        ("カスタマーサポート業務の移管について", ["移管"]),
        ("旧プランの新規受付停止のお知らせ", ["新規受付停止"]),
    ])
    def test_matches(self, title, expected):
        assert sorted(prtimes.match_keywords(title)) == sorted(expected)

    @pytest.mark.parametrize("title", [
        "新サービスを開始しました",
        "資金調達を実施 シリーズAで5億円",
        "夏の新商品発売のお知らせ",
        # 意図的除外の確認: 単体「統合」「改定」は複合語のみマッチ
        "システム統合基盤をリリース",
        "利用規約改定のお知らせ",
    ])
    def test_no_match(self, title):
        assert prtimes.match_keywords(title) == []


class TestPrtimesMatchRelease:
    def test_title_hit_takes_precedence(self):
        matched, where = prtimes.match_release("値上げのお知らせ", "本文でもサービス終了に言及")
        assert matched == ["値上げ"]
        assert where == "title"

    def test_description_hit(self):
        matched, where = prtimes.match_release(
            "重要なお知らせ", "誠に勝手ながら本サービスの提供終了を決定いたしました")
        assert matched == ["提供終了"]
        assert where == "description"

    def test_no_hit(self):
        assert prtimes.match_release("新商品のご案内", "夏の新作です") == ([], "")


class TestPrtimesParseFeed:
    def test_parse_rdf(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
            ' xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<item><title>テストのサービス終了</title>'
            '<link>https://prtimes.jp/main/html/rd/p/000000001.000000001.html</link>'
            '<description>説明文</description>'
            '<dc:date>2026-07-23T12:00:00+09:00</dc:date></item>'
            "</rdf:RDF>"
        ).encode("utf-8")
        items = prtimes.parse_feed(xml)
        assert len(items) == 1
        assert items[0]["title"] == "テストのサービス終了"
        assert items[0]["link"].startswith("https://prtimes.jp/")
        assert items[0]["date"] == "2026-07-23T12:00:00+09:00"


# ──────────────────────────────────────────────
# youtube: ニーズ語正規表現
# ──────────────────────────────────────────────
class TestYoutubeNeedPatterns:
    @pytest.mark.parametrize("text", [
        "こういうアプリないかな",
        "いいアプリがなくて困ってます",
        "アプリ探しに疲れた",
        "こういうツールないですか",
        "誰か作ってほしい",
        "こんな機能あったらいいのに",
        "有料でも使いたいレベル",
        "みんなどうやって管理してるの?",
        "この作業を自動化したい",
    ])
    def test_matches(self, text):
        assert youtube.match_needs(text) != []

    @pytest.mark.parametrize("text", [
        "面白かったです!",
        "このアプリ最高",
        "チャンネル登録しました",
        "автоматизация",
        # 2026-07-26: 実データで誤爆した叙述表現 (依頼ではない)
        "大変な思いをして作ってくれている人がいると思うと",
        "母が作ってくれたお弁当",
    ])
    def test_no_match(self, text):
        assert youtube.match_needs(text) == []

    @pytest.mark.parametrize("text", [
        "誰か作ってほしい",
        "こういうの作ってください",
        "作ってくれないかな",
    ])
    def test_request_forms_still_match(self, text):
        assert youtube.match_needs(text) != []

    def test_returns_matched_pattern_strings(self):
        matched = youtube.match_needs("自動化したいです")
        assert all(isinstance(p, str) for p in matched)
        assert any("自動化" in p for p in matched)


class TestYoutubeTiers:
    """2層パターン (2026-07-26): HIGHを1つでも含めば high、LOWのみなら low。"""

    @pytest.mark.parametrize("text", [
        "おすすめの家計簿アプリを教えてください",  # 文脈必須型「教えて」
        "確定申告のやり方を教えてほしいです",
        "こういうツールないですか",
        "この作業を自動化したい",
    ])
    def test_high(self, text):
        matched = youtube.match_needs(text)
        assert matched != []
        assert youtube.classify_tier(matched) == "high"

    @pytest.mark.parametrize("text", [
        "次の動画はいつですか？教えてください",  # 文脈なしの丁寧な依頼
        "どうすればいいですか",
    ])
    def test_low(self, text):
        matched = youtube.match_needs(text)
        assert matched != []
        assert youtube.classify_tier(matched) == "low"


class TestYoutubeCommentAge:
    def test_z_suffix_iso(self):
        from datetime import datetime, timezone
        now = datetime(2021, 5, 2, 12, 34, 56, tzinfo=timezone.utc)
        assert youtube.comment_age_days("2021-05-01T12:34:56Z", now=now) == 1

    def test_future_clamped_to_zero(self):
        from datetime import datetime, timezone
        now = datetime(2021, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert youtube.comment_age_days("2021-05-02T00:00:00Z", now=now) == 0

    @pytest.mark.parametrize("value", [None, "", "unknown", "2021/05/01"])
    def test_unparsable_returns_none(self, value):
        assert youtube.comment_age_days(value) is None


class TestYoutubeChannelRss:
    FEED = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
        "<title>チャンネル名</title>"
        "<entry><yt:videoId>vid_new01</yt:videoId><title>新しい動画</title>"
        "<published>2026-07-20T09:00:00+00:00</published></entry>"
        "<entry><yt:videoId>vid_old01</yt:videoId><title>古い動画</title>"
        "<published>2025-01-01T09:00:00+00:00</published></entry>"
        "</feed>"
    ).encode("utf-8")

    def test_parse(self):
        entries = youtube.parse_channel_rss(self.FEED)
        assert [e["video_id"] for e in entries] == ["vid_new01", "vid_old01"]
        assert entries[0]["title"] == "新しい動画"
        assert entries[0]["published"] == "2026-07-20T09:00:00+00:00"


class TestYoutubeSelectRecentVideos:
    def _entry(self, vid: str, published: str) -> dict:
        return {"video_id": vid, "title": "t", "published": published}

    def test_default_no_age_window(self):
        # v3.2: 既定は日数フィルタなし (evergreen動画のコメントが主要な信号源のため)
        from datetime import datetime, timezone
        now = datetime(2026, 7, 26, 0, 0, 0, tzinfo=timezone.utc)
        entries = [
            self._entry("recent", "2026-07-01T00:00:00+00:00"),
            self._entry("old_evergreen", "2020-01-01T00:00:00+00:00"),  # 6年前でも含める
        ]
        selected = youtube.select_recent_videos(entries, now=now)
        assert [e["video_id"] for e in selected] == ["recent", "old_evergreen"]

    def test_explicit_age_window_filters(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 26, 0, 0, 0, tzinfo=timezone.utc)
        entries = [
            self._entry("recent", "2026-07-01T00:00:00+00:00"),   # 25日前
            self._entry("too_old", "2026-01-01T00:00:00+00:00"),  # 90日超
            self._entry("no_date", ""),
        ]
        selected = youtube.select_recent_videos(entries, max_age_days=90, now=now)
        assert [e["video_id"] for e in selected] == ["recent"]

    def test_limits_per_channel_and_sorts_newest_first(self):
        from datetime import datetime, timezone
        now = datetime(2026, 7, 26, 0, 0, 0, tzinfo=timezone.utc)
        entries = [
            self._entry(f"v{i}", f"2026-07-{10 + i:02d}T00:00:00+00:00") for i in range(7)
        ]
        selected = youtube.select_recent_videos(entries, per_channel=5, now=now)
        assert [e["video_id"] for e in selected] == ["v6", "v5", "v4", "v3", "v2"]


class TestYoutubeMergeVideoTargets:
    def test_rss_and_pinned_merge(self):
        targets = youtube.merge_video_targets(
            [("vidA", "UC_ch1"), ("vidB", "UC_ch2")],
            ["vidP"],
        )
        assert targets == [
            ("vidA", "UC_ch1", "channel_rss"),
            ("vidB", "UC_ch2", "channel_rss"),
            ("vidP", "", "pinned"),
        ]

    def test_pinned_duplicate_of_rss_not_revisited(self):
        # 同一動画がRSSと固定の両方に載る場合はRSS由来を優先し重複巡回しない
        targets = youtube.merge_video_targets([("vidA", "UC_ch1")], ["vidA", "vidP"])
        assert targets == [("vidA", "UC_ch1", "channel_rss"), ("vidP", "", "pinned")]

    def test_empty_inputs(self):
        assert youtube.merge_video_targets([], []) == []


# ──────────────────────────────────────────────
# laws: 施行日窓判定 / 月加算
# ──────────────────────────────────────────────
class TestLawsWindow:
    WINDOW = (date(2026, 10, 23), date(2026, 12, 23))

    def test_enforcement_date_inside_window(self):
        rev = {"amendment_enforcement_date": "2026-11-01"}
        assert laws.enforcement_date_in_window(rev, *self.WINDOW) == "2026-11-01"

    def test_window_boundaries_inclusive(self):
        assert laws.enforcement_date_in_window(
            {"amendment_enforcement_date": "2026-10-23"}, *self.WINDOW) == "2026-10-23"
        assert laws.enforcement_date_in_window(
            {"amendment_enforcement_date": "2026-12-23"}, *self.WINDOW) == "2026-12-23"

    def test_outside_window(self):
        assert laws.enforcement_date_in_window(
            {"amendment_enforcement_date": "2026-10-22"}, *self.WINDOW) is None
        assert laws.enforcement_date_in_window(
            {"amendment_enforcement_date": "2026-12-24"}, *self.WINDOW) is None

    def test_scheduled_date_fallback(self):
        rev = {
            "amendment_enforcement_date": "2025-04-01",
            "amendment_scheduled_enforcement_date": "2026-11-15",
        }
        assert laws.enforcement_date_in_window(rev, *self.WINDOW) == "2026-11-15"

    def test_missing_or_invalid_dates(self):
        assert laws.enforcement_date_in_window({}, *self.WINDOW) is None
        assert laws.enforcement_date_in_window(
            {"amendment_enforcement_date": "unknown"}, *self.WINDOW) is None


class TestAddMonths:
    def test_simple(self):
        assert laws.add_months(date(2026, 7, 23), 3) == date(2026, 10, 23)

    def test_year_rollover(self):
        assert laws.add_months(date(2026, 10, 15), 5) == date(2027, 3, 15)

    def test_end_of_month_clamp(self):
        # 1/31 + 3ヶ月 → 4/30 (4/31は存在しない)
        assert laws.add_months(date(2026, 1, 31), 3) == date(2026, 4, 30)
        # 11/30 + 3ヶ月 → 2/28 (平年)
        assert laws.add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


# ──────────────────────────────────────────────
# gplay: レビュー→信号変換 (ネットワーク不要)
# ──────────────────────────────────────────────
class TestGplayReviewToSignal:
    def test_converts_review(self):
        from datetime import datetime
        review = {
            "reviewId": "rev-123",
            "content": "全然同期できない",
            "score": 1,
            "at": datetime(2026, 7, 20, 10, 0, 0),
            "thumbsUpCount": 5,
            "appVersion": "2.3.1",
        }
        sig = gplay.review_to_signal("com.example.app", review)
        assert sig["source"] == "gplay"
        assert sig["native_id"] == "rev-123"
        assert sig["raw_category"] == "score_1"
        assert sig["body"] == "全然同期できない"
        assert sig["meta"]["app_id"] == "com.example.app"
        assert sig["meta"]["reviewed_at"] == "2026-07-20T10:00:00"
        assert sig["meta"]["complaint_tags"] == ["bug"]


class TestGplayClassifyComplaint:
    @pytest.mark.parametrize("body,expected", [
        ("誤タップ誘発の広告が多すぎる", ["ads"]),
        ("アップデート後に起動しない", ["bug"]),
        ("機種変したらデータの引き継ぎができない", ["auth"]),
        ("月額が高すぎる。無料版の機能も減った", ["price"]),
        ("問い合わせても返信がない", ["support"]),
    ])
    def test_single_tag(self, body, expected):
        assert gplay.classify_complaint(body) == expected

    def test_multi_tag(self):
        tags = gplay.classify_complaint("ログインできず、サポートに問い合わせても返答なし")
        assert tags == ["auth", "support"]

    def test_domain_pain_falls_to_other(self):
        # 機械分類に該当しない不満 = ドメイン不満候補としてトリアージ対象
        assert gplay.classify_complaint("圃場の区画分けが手入力でしかできない") == ["other"]

    def test_empty_body(self):
        assert gplay.classify_complaint("") == ["other"]
