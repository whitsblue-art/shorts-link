import base64
from datetime import datetime, timezone
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from shopping.core import GateError, AIUnavailable, Journal, fingerprint, require_pass
from shopping.ai import AI
from shopping.coupang import authorization, normalize_product, Coupang, PREFIX
from shopping.catalogue import make_entry, merge_products, verify_live
from shopping.channel import resolve_channel, public_channel
from shopping.pipeline import verified_files
from shopping.publish import Publisher, connect_youtube
from shopping.state import Ledger, validate_catalogue
from shopping import assets, design, media, script


def product():
    return {"product_id": "123", "title": "360도 회전 코브라 수전 헤드", "affiliate_link": "https://link.coupang.com/a/test",
        "reference_image": "https://thumbnail.coupangcdn.com/a.jpg", "canonical_url": "https://www.coupang.com/vp/products/123"}


def meta():
    narrations = [
        "싱크대에서 사용할 수전을 찾고 계신가요? 삼백육십 도 회전 코브라 수전 헤드를 소개합니다. 설치 조건과 옵션은 상품 페이지에서 먼저 확인해 주세요.",
        "회전하는 코브라 형태의 수전 헤드입니다. 사용 중인 수전에 맞는지 연결 규격을 확인해 주세요. 구체적인 구성과 설치 조건도 상세 페이지에서 살펴보세요.",
        "상품이 궁금하시다면 프로필 링크에서 15번을 검색해 주세요. 현재 판매 옵션과 호환 조건을 자세히 확인하고 우리 집에 맞는 제품인지 비교해 보세요."]
    return {"title": "코브라 수전 헤드 살펴보기", "description": "제품 옵션을 확인하세요.", "thumbnail_text": "회전 수전 헤드", "product_title": product()["title"],
        "upload_description": "description", "scenes": [{"scene_num": i, "narration": text, "badge": "추천 꿀템 NO.15",
            "hook": "회전 수전 헤드", "sub": "프로필 링크에서 [15번] 검색!", "visual_prompt": "Exact cobra faucet head", "media_kind": "image"} for i, text in enumerate(narrations, 1)]}


def episode():
    return {"id": "a" * 24, "catalogue_id": 15, "format": "shorts", "product": product(), "meta": meta(),
        "qa_passed": True, "qa_provider":"openai", "qa_version":2, "publication_allowed": True, "status": "verified", "poster_hashes": ["a", "b", "c"]}


class ShoppingTests(unittest.TestCase):
    def test_quota_failure_stops_without_retrying_or_approving(self):
        response=Mock(status_code=429)
        with patch.dict(os.environ, {"OPENAI_API_KEY":"test-only-key"}), patch('shopping.ai.requests.post',return_value=response) as post, patch('shopping.ai.time.sleep') as sleep:
            with self.assertRaises(AIUnavailable):
                AI().json('test')
            self.assertEqual(post.call_count,1)
            sleep.assert_not_called()

    def test_quota_failure_does_not_become_product_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)
            def save(url,target,**kwargs):
                Image.new('RGB',(400,400),'white').save(target)
            candidates=[{'url':'https://example.org/a.jpg','type':'image','publication_allowed':True}]
            with patch('shopping.assets.save_image',side_effect=save), patch('shopping.assets.discover',return_value=candidates), patch('shopping.assets.validate_product_media',side_effect=AIUnavailable('quota')):
                with self.assertRaises(AIUnavailable):
                    assets.collect(Mock(),product(),[],{},directory)
            self.assertFalse((directory/'assets.json').exists())
    def test_malformed_registered_token_rejects_without_logging_value(self):
        for raw in ('C:/private/shopping_youtube_token.json', '{"refresh_token":"private-value"'):
            with patch.dict(os.environ, {"SHOPPING_YOUTUBE_TOKEN_JSON": raw}):
                with self.assertRaisesRegex(GateError, "not valid JSON") as caught:
                    connect_youtube()
                self.assertNotIn("private", str(caught.exception))

    def test_client_download_is_not_a_channel_token(self):
        with patch.dict(os.environ, {"SHOPPING_YOUTUBE_TOKEN_JSON": '{"installed":{"client_secret":"private-value"}}'}):
            with self.assertRaisesRegex(GateError, "Client-secret JSON was registered") as caught:
                connect_youtube()
            self.assertNotIn("private-value", str(caught.exception))
    def test_repository_config_contract(self):
        root = Path(__file__).resolve().parent.parent
        config = json.loads((root / "shopping_config.json").read_text(encoding="utf-8"))
        self.assertTrue(config["catalogue_base_url"].startswith("https://"))
        self.assertTrue(config["keywords"])
        self.assertTrue(all(isinstance(word, str) and word.strip() for word in config["keywords"]))

    def test_approved_source_matches_origin_and_path_boundary(self):
        prefixes = ["https://reviews.example/approved"]
        self.assertTrue(assets.allowed_source("https://reviews.example/approved/video", prefixes))
        self.assertFalse(assets.allowed_source("https://reviews.example/approved-malicious", prefixes))
        self.assertFalse(assets.allowed_source("https://reviews.example.evil.org/approved", prefixes))

    def test_public_channel_requires_actual_metadata(self):
        response = Mock(status_code=200, text='{"channelMetadataRenderer":{"title":"살림발견","externalId":"UCr2J97efKeupnbuk642zksg"}}')
        with patch("shopping.channel.requests.get", return_value=response):
            identity = public_channel("https://www.youtube.com/@salimfind83")
            self.assertEqual(identity["title"], "살림발견")
            response.text = '<html>Verify you are human</html>'
            with self.assertRaises(GateError):
                public_channel("https://www.youtube.com/@salimfind83")

    def test_different_oauth_channel_cannot_bind_or_upload(self):
        journal = Mock()
        journal.data = Journal.empty()
        youtube = Mock()
        youtube.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": "UC" + "x" * 22,
            "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}
        with patch("shopping.publish.resolve_channel", return_value="UCr2J97efKeupnbuk642zksg"):
            with self.assertRaises(GateError):
                Publisher(journal, youtube=youtube)
        journal.save.assert_not_called()
        youtube.videos.assert_not_called()

    def test_environment_override_cannot_redirect_pinned_channel(self):
        journal = Mock()
        journal.data = Journal.empty()
        wrong = "UC" + "x" * 22
        youtube = Mock()
        youtube.channels.return_value.list.return_value.execute.return_value = {"items": [{"id": wrong,
            "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}}}]}
        with patch("shopping.publish.resolve_channel", return_value=wrong):
            with self.assertRaisesRegex(GateError, "verified shopping channel ID"):
                Publisher(journal, youtube=youtube)
        journal.save.assert_not_called()
    def test_hmac_uses_exact_query_and_utc(self):
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        path, query = PREFIX + "/products/search", "keyword=%EC%88%98%EC%A0%84&limit=1"
        expected = hmac.new(b"secret", ("260102T030405ZGET" + path + query).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(authorization("get", path, query, "access", "secret", now),
            "CEA algorithm=HmacSHA256, access-key=access, signed-date=260102T030405Z, signature=" + expected)

    def test_normalize_exact_variant(self):
        raw = {"productId": 123, "productName": "test", "productImage": "https://cdn.example/a.jpg",
            "productUrl": "https://link.coupang.com/re/AFFSDP?itemId=45&vendorItemId=67&pageKey=123"}
        self.assertEqual(normalize_product(raw)["canonical_url"], "https://www.coupang.com/vp/products/123?itemId=45&vendorItemId=67")
        raw["productUrl"] = "https://link.coupang.com/?pageKey=999"
        with self.assertRaises(GateError):
            normalize_product(raw)

    def test_deeplink_never_substitutes_search_link(self):
        api = Coupang("access", "secret")
        api.request = Mock(return_value=[{"originalUrl": "wrong", "shortenUrl": "https://link.coupang.com/a/test"}])
        with self.assertRaises(GateError):
            api.deeplink(product())
        api.request.return_value = [{"originalUrl": product()["canonical_url"], "shortenUrl": "https://evil.com/a"}]
        with self.assertRaises(GateError):
            api.deeplink(product())

    def test_api_error_never_passes_or_exposes_secret(self):
        api = Coupang("private-access", "private-secret")
        response = Mock(status_code=403)
        with patch("shopping.coupang.requests.request", return_value=response):
            with self.assertRaises(GateError) as caught:
                api.search("수전")
        self.assertNotIn("private", str(caught.exception))

    def test_missing_review_checks_reject(self):
        for value in ({"verdict": "PASS", "checks": {}}, {"verdict": "UNKNOWN", "checks": {"same_model": "PASS"}}):
            with self.assertRaises(GateError):
                require_pass(value, ["same_model"])

    def test_known_negative_images_blocked_before_network(self):
        for number in assets.BAD_IMAGES:
            with patch("shopping.assets.fetch") as fetch:
                with self.assertRaises(GateError):
                    assets.save_image("https://images.unsplash.com/photo-" + number, Path("unused.jpg"))
                fetch.assert_not_called()

    def test_three_distinct_media_or_no_success(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            def save(url, target, **kwargs):
                Image.new("RGB", (400, 400), "white").save(target)
            candidates = [{"url": f"https://example.org/{n}.jpg", "type": "image", "publication_allowed": True} for n in range(3)]
            with patch("shopping.assets.save_image", side_effect=save), patch("shopping.assets.discover", return_value=candidates), patch("shopping.assets.validate_product_media", return_value={"verdict": "PASS"}):
                with self.assertRaisesRegex(GateError, "Only 1 distinct"):
                    assets.collect(Mock(), product(), [], {}, directory)
            self.assertFalse((directory / "assets.json").exists())

    def test_unapproved_review_not_used_for_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            candidates = [{"url": "https://example.org/review.mp4", "type": "video", "publication_allowed": False}]
            with patch("shopping.assets.save_image"), patch("shopping.assets.discover", return_value=candidates), patch("shopping.assets.fetch") as fetch:
                with self.assertRaises(GateError):
                    assets.collect(Mock(), product(), [], {}, Path(temp), for_publication=True)
                fetch.assert_not_called()

    def test_reference_candidate_labels(self):
        ai = Mock()
        with patch("shopping.assets.image_part", side_effect=lambda p: {"image": str(p)}):
            assets.validate_product_media(ai, product(), "reference", ["candidate"], "title")
        attachments = ai.judge.call_args.args[2]
        self.assertIn("TARGET", attachments[0]["text"])
        self.assertIn("CANDIDATE", attachments[2]["text"])

    def test_script_number_and_claims(self):
        script.validate(meta(), 15)
        bad = meta()
        bad["scenes"][-1]["sub"] = "프로필 16번"
        with self.assertRaises(GateError):
            script.validate(bad, 15)
        bad = meta()
        bad["scenes"][0]["hook"] = "최저가"
        with self.assertRaises(GateError):
            script.validate(bad, 15)

    def test_legacy_history_preserved_and_wrong_image_quarantined(self):
        original = [{"id": 14, "title": "old", "verified": True, "image": "https://example.org/1556911220"}]
        entry = make_entry(episode(), meta(), "https://whitsblue-art.github.io/shorts-link/")
        rows = merge_products(original, entry)
        self.assertEqual([r["id"] for r in rows], [15, 14])
        self.assertFalse(rows[1]["verified"])
        self.assertTrue(original[0]["verified"])
        self.assertEqual(len(set(s["image"] for s in rows[0]["scenes"])), 3)
        self.assertEqual(len(merge_products(rows, entry)), 2)

    def test_catalogue_conflict_never_overwrites(self):
        entry = make_entry(episode(), meta(), "https://example.org/")
        conflict = {**entry, "coupang_product_id": "999"}
        with self.assertRaises(GateError):
            merge_products([conflict], entry)
        with self.assertRaises(GateError):
            validate_catalogue([entry, entry])

    def test_next_number_after_fourteen(self):
        ledger = Ledger.__new__(Ledger)
        ledger.data = Journal.empty()
        self.assertEqual(ledger.next_number([{"id": 14}]), 15)
        ledger.data["episodes"]["one"] = {"status": "rejected", "catalogue_id": 15}
        self.assertEqual(ledger.next_number([{"id": 14}]), 15)

    def test_live_catalogue_mismatch_blocks(self):
        row = episode()
        row["catalogue_entry"] = make_entry(row, meta(), "https://example.org/")
        response = Mock(status_code=200)
        response.json.return_value = []
        with patch("shopping.catalogue.requests.get", return_value=response):
            with self.assertRaises(GateError):
                verify_live(row, "https://example.org/")

    def test_modified_verified_file_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "video.mp4").write_bytes(b"changed")
            row = {"qa_passed": True, "qa_provider":"openai", "qa_version":2, "asset_hashes": {"video.mp4": fingerprint(b"reviewed")}}
            with self.assertRaises(GateError):
                verified_files(row, directory)

    def test_missing_catalogue_gate_blocks_before_upload(self):
        publisher = Publisher.__new__(Publisher)
        publisher.catalogue_gate = None
        publisher.youtube = Mock()
        with self.assertRaises(GateError):
            publisher.upload(episode(), None, meta())
        publisher.youtube.videos.assert_not_called()

    def test_uncertain_upload_never_inserts_again(self):
        publisher = Publisher.__new__(Publisher)
        publisher.catalogue_gate = Mock()
        publisher.recover = Mock(return_value=None)
        publisher.youtube = Mock()
        row = {**episode(), "status": "upload_unknown"}
        with self.assertRaisesRegex(GateError, "No second upload"):
            publisher.upload(row, None, meta())
        publisher.youtube.videos.assert_not_called()

    def test_upload_intent_is_durable_before_insert(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"reviewed fixture")
            row = {**episode(), "video_sha256": fingerprint(path.read_bytes())}
            publisher = Publisher.__new__(Publisher)
            publisher.catalogue_gate = Mock()
            publisher.recover = Mock(return_value=None)
            publisher.journal = Mock()
            publisher.youtube = Mock()
            events = []
            publisher.journal.update.side_effect = lambda e, **kw: events.append(kw["status"])
            def insert(**kwargs):
                events.append("insert")
                request = Mock()
                request.next_chunk.return_value = (None, {"id": "test-video"})
                return request
            publisher.youtube.videos.return_value.insert.side_effect = insert
            self.assertEqual(publisher.upload(row, path, meta()), "test-video")
            self.assertEqual(events, ["uploading", "insert", "uploaded"])

    def test_failed_intent_write_prevents_insert(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"fixture")
            publisher = Publisher.__new__(Publisher)
            publisher.catalogue_gate = Mock()
            publisher.recover = Mock(return_value=None)
            publisher.journal = Mock()
            publisher.journal.update.side_effect = GateError("Durable write failed")
            publisher.youtube = Mock()
            with self.assertRaises(GateError):
                publisher.upload({**episode(), "video_sha256": fingerprint(path.read_bytes())}, path, meta())
            publisher.youtube.videos.assert_not_called()

    def test_channel_id_and_untrusted_host(self):
        youtube = Mock()
        channel = "UC" + "a" * 22
        self.assertEqual(resolve_channel(youtube, "https://www.youtube.com/channel/" + channel), channel)
        with self.assertRaises(GateError):
            resolve_channel(youtube, "https://youtube.com.evil.org/@channel")

    def test_subtitle_ocr_ignores_spaces_but_preserves_numbers(self):
        media.compare_subtitle_text(["프로필 링크에서", "15번 검색!"], "프로필링크에서 15번 검색!")
        with self.assertRaises(GateError):
            media.compare_subtitle_text(["15번 검색!"], "16번 검색!")

    def test_invalid_word_timing_rejects(self):
        with self.assertRaises(GateError):
            media.validate_boundaries([], "안녕", 3)
        with self.assertRaises(GateError):
            media.validate_boundaries([{"start": 0, "end": 1, "text": "다른 내용"}], "안녕", 3)

    def test_import_does_not_run_services(self):
        with patch("shopping.coupang.requests.request") as request:
            import main
            importlib.reload(main)
            request.assert_not_called()


class RealRenderTests(unittest.TestCase):
    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "ffmpeg unavailable")
    def test_real_three_scene_image_and_video_render_cfr(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            document = meta()
            timings = []
            for n, scene in enumerate(document["scenes"], 1):
                image = Image.new("RGB", (600, 600), (50 * n, 130, 180))
                from PIL import ImageDraw
                ImageDraw.Draw(image).rectangle((n * 60, 80, n * 60 + 180, 500), fill="white")
                image.save(directory / f"scene_{n:02d}.jpg")
                # Synthetic tone is a renderer fixture only; production always requires reviewed TTS.
                media.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=400:sample_rate=48000", "-t", "1.113", str(directory / f"voice_{n:02d}.mp3")])
                scene["narration"] = f"테스트 {n}번"
                timings.append([{"start": .1, "end": .8, "text": scene["narration"]}])
            document["scenes"][1]["media_kind"] = "video"
            media.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(directory / "scene_02.jpg"), "-t", "0.7", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(directory / "scene_02.mp4")])
            # Stale rejected video must be ignored when the accepted kind is image.
            (directory / "scene_01.mp4").write_bytes(b"invalid rejected candidate")
            final, manifest = design.render(document, directory, timings)
            report = media.validate_video(final, manifest, media.Profile(1080, 1920, 30, 1, 10))
            self.assertEqual(len(manifest["scene_durations"]), 3)
            self.assertGreater(report["duration"], 3)
            self.assertTrue((directory / "subtitles.srt").exists())


if __name__ == "__main__":
    unittest.main()
