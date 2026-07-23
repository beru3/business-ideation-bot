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
    ])
    def test_matches(self, title, expected):
        assert sorted(prtimes.match_keywords(title)) == sorted(expected)

    @pytest.mark.parametrize("title", [
        "新サービスを開始しました",
        "資金調達を実施 シリーズAで5億円",
        "夏の新商品発売のお知らせ",
    ])
    def test_no_match(self, title):
        assert prtimes.match_keywords(title) == []


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
    ])
    def test_no_match(self, text):
        assert youtube.match_needs(text) == []

    def test_returns_matched_pattern_strings(self):
        matched = youtube.match_needs("自動化したいです")
        assert all(isinstance(p, str) for p in matched)
        assert any("自動化" in p for p in matched)


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
