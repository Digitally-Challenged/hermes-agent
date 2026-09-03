"""Tests for the BlueBubbles iMessage gateway adapter."""
import asyncio
import json

import pytest

from gateway.config import Platform, PlatformConfig


def _make_adapter(monkeypatch, **extra):
    monkeypatch.setenv("BLUEBUBBLES_SERVER_URL", "http://localhost:1234")
    monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "secret")
    from gateway.platforms.bluebubbles import BlueBubblesAdapter

    cfg = PlatformConfig(
        enabled=True,
        extra={
            "server_url": "http://localhost:1234",
            "password": "secret",
            **extra,
        },
    )
    return BlueBubblesAdapter(cfg)


class TestBlueBubblesConfigLoading:
    def test_apply_env_overrides_bluebubbles(self, monkeypatch):
        monkeypatch.setenv("BLUEBUBBLES_SERVER_URL", "http://localhost:1234")
        monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "secret")
        monkeypatch.setenv("BLUEBUBBLES_WEBHOOK_PORT", "9999")
        monkeypatch.setenv("BLUEBUBBLES_REQUIRE_MENTION", "true")
        monkeypatch.setenv("BLUEBUBBLES_MENTION_PATTERNS", r'["(?i)^amos\\b"]')
        from gateway.config import GatewayConfig, _apply_env_overrides

        config = GatewayConfig()
        _apply_env_overrides(config)
        assert Platform.BLUEBUBBLES in config.platforms
        bc = config.platforms[Platform.BLUEBUBBLES]
        assert bc.enabled is True
        assert bc.extra["server_url"] == "http://localhost:1234"
        assert bc.extra["password"] == "secret"
        assert bc.extra["webhook_port"] == 9999
        assert bc.extra["require_mention"] is True
        assert bc.extra["mention_patterns"] == ["(?i)^amos\\b"]


class TestBlueBubblesHelpers:
    def test_check_requirements(self, monkeypatch):
        monkeypatch.setenv("BLUEBUBBLES_SERVER_URL", "http://localhost:1234")
        monkeypatch.setenv("BLUEBUBBLES_PASSWORD", "secret")
        from gateway.platforms.bluebubbles import check_bluebubbles_requirements

        assert check_bluebubbles_requirements() is True


    def test_format_message_preserves_underscores_in_identifiers(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        text = "Use /api_v2 with FEATURE_FLAG_NAME and config_file.json"
        assert adapter.format_message(text) == text

    def test_strip_markdown_headers(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        assert adapter.format_message("## Heading\ntext") == "Heading\ntext"


    def test_init_normalizes_webhook_path(self, monkeypatch):
        adapter = _make_adapter(monkeypatch, webhook_path="bluebubbles-webhook")
        assert adapter.webhook_path == "/bluebubbles-webhook"


    def test_server_url_normalized(self, monkeypatch):
        adapter = _make_adapter(monkeypatch, server_url="http://localhost:1234/")
        assert adapter.server_url == "http://localhost:1234"


def _webhook_token_for(password="secret"):
    import hashlib
    return hashlib.sha256(f"hermes-bluebubbles-webhook:{password}".encode()).hexdigest()[:32]


class _FakeBlueBubblesRequest:
    def __init__(self, payload, password="secret", query=None):
        # BB posts to the exact URL we registered, which carries the derived
        # token -- never the raw password.
        self.query = query if query is not None else {"token": _webhook_token_for(password)}
        self.headers = {}
        self._body = json.dumps(payload).encode("utf-8")

    async def read(self):
        return self._body


class TestBlueBubblesMentionGating:
    @pytest.mark.asyncio
    async def test_group_message_without_mention_is_acknowledged_and_skipped(self, monkeypatch):
        adapter = _make_adapter(
            monkeypatch,
            require_mention=True,
            send_read_receipts=False,
        )
        handled = []

        async def fake_handle_message(event):
            handled.append(event)

        monkeypatch.setattr(adapter, "handle_message", fake_handle_message)
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-1",
                "text": "casual family chatter",
                "handle": {"address": "+15555550100"},
                "isFromMe": False,
                "isGroup": True,
                "chats": [{"guid": "iMessage;+;group-chat"}],
            },
        }))
        await asyncio.sleep(0)

        assert response.status == 200
        assert handled == []


class TestBlueBubblesWebhookParsing:

    def test_webhook_can_fall_back_to_sender_when_chat_fields_missing(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        payload = {
            "data": {
                "guid": "MESSAGE-GUID",
                "text": "hello",
                "handle": {"address": "user@example.com"},
                "isFromMe": False,
            }
        }
        record = adapter._extract_payload_record(payload) or {}
        chat_guid = adapter._value(
            record.get("chatGuid"),
            payload.get("chatGuid"),
            record.get("chat_guid"),
            payload.get("chat_guid"),
            payload.get("guid"),
        )
        chat_identifier = adapter._value(
            record.get("chatIdentifier"),
            record.get("identifier"),
            payload.get("chatIdentifier"),
            payload.get("identifier"),
        )
        sender = (
            adapter._value(
                record.get("handle", {}).get("address")
                if isinstance(record.get("handle"), dict)
                else None,
                record.get("sender"),
                record.get("from"),
                record.get("address"),
            )
            or chat_identifier
            or chat_guid
        )
        if not (chat_guid or chat_identifier) and sender:
            chat_identifier = sender
        assert chat_identifier == "user@example.com"


    def test_extract_payload_record_accepts_list_data(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        payload = {
            "type": "new-message",
            "data": [
                {
                    "text": "hello",
                    "chatGuid": "iMessage;-;user@example.com",
                    "chatIdentifier": "user@example.com",
                }
            ],
        }
        record = adapter._extract_payload_record(payload)
        assert record == payload["data"][0]


class TestBlueBubblesGuidResolution:


    @pytest.mark.asyncio
    async def test_participant_only_match_does_not_resolve_to_group(self, monkeypatch):
        """Regression for #24157: contact appearing as a participant in a group
        chat must NOT be selected when no DM with that exact chatIdentifier exists.

        Otherwise an outbound DM reply leaks into the group thread.
        """
        adapter = _make_adapter(monkeypatch)

        async def fake_api_post(path, payload):
            return {
                "data": [
                    {
                        "guid": "iMessage;+;chat0000000000-family-group",
                        "chatIdentifier": "chat0000000000",
                        "participants": [
                            {"address": "user@example.com"},
                            {"address": "+15555550100"},
                        ],
                    }
                ]
            }

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        result = await adapter._resolve_chat_guid("user@example.com")
        assert result is None, (
            "participant-only match must not resolve to a group GUID — DM "
            "replies would leak into the group thread"
        )


    @pytest.mark.asyncio
    async def test_unresolved_target_is_not_cached(self, monkeypatch):
        """When no exact match is found, the resolver must NOT cache anything.

        Otherwise a later attempt — after the DM has been created — would
        keep returning the stale ``None`` from cache. Also guards against a
        latent variant of #24157 where a group GUID could be cached under a
        bare address key and persist across calls.
        """
        adapter = _make_adapter(monkeypatch)

        async def fake_api_post(path, payload):
            return {
                "data": [
                    {
                        "guid": "iMessage;+;chat0000000000-family-group",
                        "chatIdentifier": "chat0000000000",
                        "participants": [{"address": "user@example.com"}],
                    }
                ]
            }

        monkeypatch.setattr(adapter, "_api_post", fake_api_post)
        await adapter._resolve_chat_guid("user@example.com")
        assert "user@example.com" not in adapter._guid_cache


class TestBlueBubblesAttachmentDownload:
    """Verify _download_attachment routes to the correct cache helper."""

    def test_download_image_uses_image_cache(self, monkeypatch):
        """Image MIME routes to cache_image_from_bytes."""
        adapter = _make_adapter(monkeypatch)
        import asyncio

        # Mock the HTTP client response
        class MockResponse:
            status_code = 200
            content = b"\x89PNG\r\n\x1a\n"

            def raise_for_status(self):
                pass

        async def mock_get(*args, **kwargs):
            return MockResponse()

        adapter.client = type("MockClient", (), {"get": mock_get})()

        cached_path = None

        def mock_cache_image(data, ext):
            nonlocal cached_path
            cached_path = f"/tmp/test_image{ext}"
            return cached_path

        monkeypatch.setattr(
            "gateway.platforms.bluebubbles.cache_image_from_bytes",
            mock_cache_image,
        )

        att_meta = {"mimeType": "image/png", "transferName": "photo.png"}
        result = asyncio.get_event_loop().run_until_complete(
            adapter._download_attachment("att-guid-123", att_meta)
        )
        assert result == "/tmp/test_image.png"


# ---------------------------------------------------------------------------
# Webhook registration
# ---------------------------------------------------------------------------


class TestBlueBubblesWebhookUrl:
    """_webhook_url property normalises local hosts to 'localhost'."""

    def test_default_host(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        # Default webhook_host is 0.0.0.0 → normalized to localhost
        assert "localhost" in adapter._webhook_url
        assert str(adapter.webhook_port) in adapter._webhook_url
        assert adapter.webhook_path in adapter._webhook_url


    def test_register_url_omits_query_when_no_password(self, monkeypatch):
        """If no password is configured, the register URL should be the bare URL."""
        monkeypatch.delenv("BLUEBUBBLES_PASSWORD", raising=False)
        from gateway.platforms.bluebubbles import BlueBubblesAdapter
        cfg = PlatformConfig(
            enabled=True,
            extra={"server_url": "http://localhost:1234", "password": ""},
        )
        adapter = BlueBubblesAdapter(cfg)
        assert adapter._webhook_register_url == adapter._webhook_url


class TestBlueBubblesWebhookRegistration:
    """Tests for _register_webhook, _unregister_webhook, _find_registered_webhooks."""

    @staticmethod
    def _mock_client(get_response=None, post_response=None, delete_ok=True):
        """Build a tiny mock httpx.AsyncClient."""

        async def mock_get(*args, **kwargs):
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return get_response or {"status": 200, "data": []}
            return R()

        async def mock_post(*args, **kwargs):
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
                def json(self):
                    return post_response or {"status": 200, "data": {}}
            return R()

        async def mock_delete(*args, **kwargs):
            class R:
                status_code = 200 if delete_ok else 500
                def raise_for_status(self_inner):
                    if not delete_ok:
                        raise Exception("delete failed")
            return R()

        return type(
            "MockClient", (),
            {"get": mock_get, "post": mock_post, "delete": mock_delete},
        )()

    # -- _find_registered_webhooks --

    def test_find_registered_webhooks_returns_matches(self, monkeypatch):
        import asyncio
        adapter = _make_adapter(monkeypatch)
        url = adapter._webhook_url
        adapter.client = self._mock_client(
            get_response={"status": 200, "data": [
                {"id": 1, "url": url, "events": ["new-message"]},
                {"id": 2, "url": "http://other:9999/hook", "events": ["message"]},
            ]}
        )
        result = asyncio.get_event_loop().run_until_complete(
            adapter._find_registered_webhooks(url)
        )
        assert len(result) == 1
        assert result[0]["id"] == 1


    # -- _register_webhook --

    def test_register_fresh(self, monkeypatch):
        """No existing webhook → POST creates one."""
        import asyncio
        adapter = _make_adapter(monkeypatch)
        adapter.client = self._mock_client(
            get_response={"status": 200, "data": []},
            post_response={"status": 200, "data": {"id": 42}},
        )
        ok = asyncio.get_event_loop().run_until_complete(
            adapter._register_webhook()
        )
        assert ok is True


    def test_register_reuses_existing(self, monkeypatch):
        """Crash resilience — existing registration is reused, no POST needed."""
        import asyncio
        adapter = _make_adapter(monkeypatch)
        url = adapter._webhook_register_url
        adapter.client = self._mock_client(
            get_response={"status": 200, "data": [
                {"id": 7, "url": url, "events": ["new-message"]},
            ]},
        )

        # Track whether POST was called
        post_called = False
        orig_api_post = adapter._api_post
        async def tracking_post(path, payload):
            nonlocal post_called
            post_called = True
            return await orig_api_post(path, payload)
        adapter._api_post = tracking_post

        ok = asyncio.get_event_loop().run_until_complete(
            adapter._register_webhook()
        )
        assert ok is True
        assert not post_called, "Should reuse existing, not POST again"


    # -- _unregister_webhook --


    def test_unregister_removes_all_duplicates(self, monkeypatch):
        """Multiple orphaned registrations for same URL — all get removed."""
        import asyncio
        adapter = _make_adapter(monkeypatch)
        url = adapter._webhook_register_url
        deleted_ids = []

        async def mock_delete(*args, **kwargs):
            # Extract ID from URL
            url_str = args[0] if args else ""
            deleted_ids.append(url_str)
            class R:
                status_code = 200
                def raise_for_status(self):
                    pass
            return R()

        adapter.client = self._mock_client(
            get_response={"status": 200, "data": [
                {"id": 1, "url": url},
                {"id": 2, "url": url},
                {"id": 3, "url": "http://other/hook"},
            ]},
        )
        adapter.client.delete = mock_delete

        ok = asyncio.get_event_loop().run_until_complete(
            adapter._unregister_webhook()
        )
        assert ok is True
        assert len(deleted_ids) == 2


class TestBlueBubblesSelfChatGuard:
    """Self-chats (Mac and phone share one Apple ID) can't use isFromMe to
    tell the user's message apart from Hermes's own echoed reply. Listed
    chats fall through to a persistent sent-guid + content-marker guard
    instead -- see gateway/platforms/_bluebubbles_self_chat_guard.py.
    """

    SELF_GUID = "any;-;owner@example.com"

    def _make_self_chat_adapter(self, monkeypatch):
        return _make_adapter(monkeypatch, self_chat_guids=self.SELF_GUID)

    @pytest.mark.asyncio
    async def test_unlisted_chat_still_drops_is_from_me(self, monkeypatch):
        adapter = self._make_self_chat_adapter(monkeypatch)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-other-chat",
                "text": "echo from a different chat",
                "isFromMe": True,
                "chats": [{"guid": "iMessage;-;someoneelse@example.com"}],
            },
        }))
        await asyncio.sleep(0)
        assert response.status == 200
        assert handled == []

    @pytest.mark.asyncio
    async def test_self_chat_real_user_message_is_dispatched(self, monkeypatch):
        adapter = self._make_self_chat_adapter(monkeypatch)
        handled = []

        async def fake_handle_message(event):
            handled.append(event)

        monkeypatch.setattr(adapter, "handle_message", fake_handle_message)
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-from-phone",
                "text": "what model are you running",
                "isFromMe": True,
                "chats": [{"guid": self.SELF_GUID}],
            },
        }))
        await asyncio.sleep(0)
        assert response.status == 200
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_self_chat_echo_of_own_sent_guid_is_not_redispatched(self, monkeypatch):
        from gateway.platforms._bluebubbles_self_chat_guard import record_sent

        adapter = self._make_self_chat_adapter(monkeypatch)
        record_sent("msg-hermes-sent", self.SELF_GUID)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-hermes-sent",
                "text": "here is my reply",
                "isFromMe": True,
                "chats": [{"guid": self.SELF_GUID}],
            },
        }))
        await asyncio.sleep(0)
        assert response.status == 200
        assert handled == []

    @pytest.mark.asyncio
    async def test_self_chat_survives_restart_recorded_guid_still_blocks(self, monkeypatch):
        """The exact 2026-09-03 bug: a recovery redelivery sent by a PRIOR
        gateway process must still be recognized by a freshly constructed
        adapter (new process), since record_sent persists to state.db.
        """
        from gateway.platforms._bluebubbles_self_chat_guard import record_sent

        record_sent("msg-recovered-reply", self.SELF_GUID)
        # Simulate a restart: brand-new adapter instance, no shared memory
        # with whatever process called record_sent.
        adapter = self._make_self_chat_adapter(monkeypatch)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-recovered-reply",
                "text": "some earlier reply text",
                "isFromMe": True,
                "chats": [{"guid": self.SELF_GUID}],
            },
        }))
        await asyncio.sleep(0)
        assert response.status == 200
        assert handled == []

    @pytest.mark.asyncio
    async def test_self_chat_recovered_marker_text_blocked_even_without_guid_match(
        self, monkeypatch
    ):
        """Covers the race where BlueBubbles' webhook for a just-sent message
        arrives before send()'s HTTP response (and thus record_sent) lands --
        content-marker guard is the independent second line of defense.
        """
        from gateway.delivery_ledger import RECOVERED_MARKER

        adapter = self._make_self_chat_adapter(monkeypatch)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        response = await adapter._handle_webhook(_FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": "msg-not-yet-recorded",
                "text": RECOVERED_MARKER + "actual reply content",
                "isFromMe": True,
                "chats": [{"guid": self.SELF_GUID}],
            },
        }))
        await asyncio.sleep(0)
        assert response.status == 200
        assert handled == []

    @staticmethod
    def _fake_client(sent_guid="new-sent-guid"):
        class _FakeClient:
            async def post(self, url, json=None):
                class R:
                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"data": {"guid": sent_guid}}

                return R()

        return _FakeClient()

    @pytest.mark.asyncio
    async def test_send_records_guid_and_text_for_self_chat_target(self, monkeypatch):
        from gateway.platforms._bluebubbles_self_chat_guard import (
            was_sent_by_us,
            was_text_sent_recently,
        )

        adapter = self._make_self_chat_adapter(monkeypatch)
        adapter.client = self._fake_client()
        await adapter.send(self.SELF_GUID, "hi from hermes")
        assert was_sent_by_us("new-sent-guid") is True
        assert was_text_sent_recently(self.SELF_GUID, "hi from hermes") is True


class TestBlueBubblesSendBubbles:
    """One reply = one iMessage bubble. The paragraph splitter turned a
    single approval prompt into 5 bubbles in one second (2026-09-03 10:55).
    """

    @staticmethod
    def _recording_client(posts):
        class _Client:
            async def post(self, url, json=None):
                posts.append(json)

                class R:
                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"data": {"guid": f"g{len(posts)}"}}

                return R()

        return _Client()

    @pytest.mark.asyncio
    async def test_multi_paragraph_reply_is_a_single_send(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        adapter._guid_cache["any;-;+15555550100"] = "any;-;+15555550100"
        posts = []
        adapter.client = self._recording_client(posts)
        text = (
            "Dangerous command requires approval:\n\n"
            "client = make_client()\n\n"
            "prompt = 'x'\n\n"
            "Reply /approve to execute."
        )
        result = await adapter.send("any;-;+15555550100", text)
        assert result.success is True
        assert len(posts) == 1
        assert posts[0]["message"] == text

    @pytest.mark.asyncio
    async def test_over_limit_reply_is_chunked_without_pagination_suffix(self, monkeypatch):
        from gateway.platforms.bluebubbles import MAX_TEXT_LENGTH

        adapter = _make_adapter(monkeypatch)
        adapter._guid_cache["any;-;+15555550100"] = "any;-;+15555550100"
        posts = []
        adapter.client = self._recording_client(posts)
        text = "word " * (MAX_TEXT_LENGTH // 2)  # ~2.5x the limit
        result = await adapter.send("any;-;+15555550100", text)
        assert result.success is True
        assert len(posts) >= 2
        assert all(len(p["message"]) <= MAX_TEXT_LENGTH for p in posts)
        assert not any(p["message"].rstrip().endswith(")") and "/" in p["message"][-8:] for p in posts)


class TestBlueBubblesWebhookToken:
    """BlueBubbles logs the registered webhook URL to its own main.log on
    every dispatch and 1.9.9 has no way to turn that off, so the URL must
    carry a derived token -- never the API password (which reads and sends
    all iMessage). 107 plaintext copies of the live password were found in
    main.log on 2026-09-03 from the old ``?password=`` registration.
    """

    def test_registered_url_never_contains_the_password(self, monkeypatch):
        from urllib.parse import quote

        adapter = _make_adapter(monkeypatch, password="super-secret-pw")
        url = adapter._webhook_register_url
        assert "super-secret-pw" not in url
        assert quote("super-secret-pw", safe="") not in url
        assert "?token=" in url
        assert adapter._webhook_token in url

    def test_token_is_deterministic_and_not_reversible_by_inspection(self, monkeypatch):
        a = _make_adapter(monkeypatch, password="pw-one")
        b = _make_adapter(monkeypatch, password="pw-one")
        c = _make_adapter(monkeypatch, password="pw-two")
        assert a._webhook_token == b._webhook_token
        assert a._webhook_token != c._webhook_token
        assert "pw-one" not in a._webhook_token

    @pytest.mark.asyncio
    async def test_raw_password_in_query_is_rejected(self, monkeypatch):
        """The old registration form must not authenticate any more."""
        adapter = _make_adapter(monkeypatch)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        req = _FakeBlueBubblesRequest(
            {"type": "new-message", "data": {"guid": "g", "text": "hi",
             "handle": {"address": "+15555550100"},
             "chats": [{"guid": "any;-;+15555550100"}]}},
            query={"password": "secret"},
        )
        response = await adapter._handle_webhook(req)
        assert response.status == 401
        assert handled == []

    @pytest.mark.asyncio
    async def test_wrong_token_is_rejected(self, monkeypatch):
        adapter = _make_adapter(monkeypatch)
        req = _FakeBlueBubblesRequest({"type": "new-message", "data": {}}, query={"token": "nope"})
        response = await adapter._handle_webhook(req)
        assert response.status == 401

    def test_register_purges_stale_registrations_for_our_listener(self, monkeypatch):
        """A pre-rotation / legacy ?password= registration pointing at our
        listener is deleted before we register, so BB never dispatches each
        event twice. Registrations for other listeners are left alone."""
        adapter = _make_adapter(monkeypatch)
        base = adapter._webhook_url
        deleted = []

        async def mock_delete(url, *a, **k):
            deleted.append(url)

            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

            return R()

        adapter.client = TestBlueBubblesWebhookRegistration._mock_client(
            get_response={"status": 200, "data": [
                {"id": 8, "url": f"{base}?password=OLDPASSWORD"},
                {"id": 9, "url": f"{base}?token=stale-derived-token"},
                {"id": 3, "url": "http://other:9999/hook?password=x"},
            ]},
            post_response={"status": 200, "data": {"id": 14}},
        )
        adapter.client.delete = mock_delete
        ok = asyncio.get_event_loop().run_until_complete(adapter._register_webhook())
        assert ok is True
        assert sorted(d.split("/webhook/")[1].split("?")[0] for d in deleted) == ["8", "9"]


class TestBlueBubblesPasswordScrub:
    """Every request URL carries ``?password=`` and httpx's HTTPStatusError
    message includes the URL. 34 plaintext copies of the live password were
    found in gateway.log on 2026-09-03 via SendResult.error -> base logger.
    """

    @pytest.mark.asyncio
    async def test_send_failure_error_string_does_not_contain_password(self, monkeypatch):
        import httpx

        adapter = _make_adapter(monkeypatch, password="s3cr3t-pw")
        adapter._guid_cache["any;-;+15555550100"] = "any;-;+15555550100"

        class _FailingClient:
            async def post(self, url, json=None):
                req = httpx.Request("POST", url)
                resp = httpx.Response(500, request=req)
                raise httpx.HTTPStatusError("Server error", request=req, response=resp)

        adapter.client = _FailingClient()
        result = await adapter.send("any;-;+15555550100", "hello")
        assert result.success is False
        assert "s3cr3t-pw" not in result.error
        assert "password=***" in result.error or "password=" not in result.error

    def test_scrub_handles_raw_and_urlencoded_forms(self, monkeypatch):
        from urllib.parse import quote

        pw = "p@ss w/ord&x"
        adapter = _make_adapter(monkeypatch, password=pw)
        msg = f"boom http://h/api?password={quote(pw, safe='')} and raw {pw}"
        out = adapter._scrub(RuntimeError(msg))
        assert pw not in out
        assert quote(pw, safe="") not in out


class TestBlueBubblesTextEchoGuard:
    """The second 2026-09-03 loop: the Mac's iMessage identity was set to the
    same phone number the iPhone sends from, so Apple delivered every reply
    Hermes sent to ``any;-;+1...`` straight back as an INCOMING message from
    that number -- isFromMe=False, a brand-new guid, in a chat nobody had
    listed as a self-chat. Neither the isFromMe drop nor the guid guard could
    see it; Hermes answered itself every ~3s. The text-echo guard is the
    identity-independent breaker for that.
    """

    PHONE_GUID = "any;-;+15555550100"

    def _inbound(self, text, guid="msg-incoming-1", chat=None):
        return _FakeBlueBubblesRequest({
            "type": "new-message",
            "data": {
                "guid": guid,
                "text": text,
                "isFromMe": False,
                "handle": {"address": "+15555550100"},
                "chats": [{"guid": chat or self.PHONE_GUID}],
            },
        })

    @pytest.mark.asyncio
    async def test_send_records_text_for_unlisted_chat(self, monkeypatch):
        """Recording must not be gated on self_chat_guids -- the loop chat
        wasn't listed."""
        from gateway.platforms._bluebubbles_self_chat_guard import was_text_sent_recently

        adapter = _make_adapter(monkeypatch)  # no self_chat_guids at all
        adapter.client = TestBlueBubblesSelfChatGuard._fake_client()
        await adapter.send(self.PHONE_GUID, "Same. Just waiting for your next command.")
        assert was_text_sent_recently(
            self.PHONE_GUID, "Same. Just waiting for your next command."
        ) is True

    @pytest.mark.asyncio
    async def test_echo_of_own_text_with_is_from_me_false_is_dropped(self, monkeypatch):
        """The exact loop shape: our sent text comes back isFromMe=False with
        a different guid in an unlisted chat."""
        from gateway.platforms._bluebubbles_self_chat_guard import record_sent

        adapter = _make_adapter(monkeypatch)
        handled = []
        monkeypatch.setattr(adapter, "handle_message", lambda e: handled.append(e))
        record_sent("guid-we-sent", self.PHONE_GUID, "Nothing on my end. You tell me.")

        response = await adapter._handle_webhook(
            self._inbound("Nothing on my end. You tell me.", guid="guid-apple-assigned-to-echo")
        )
        await asyncio.sleep(0)
        assert response.status == 200
        assert handled == []

    @pytest.mark.asyncio
    async def test_real_user_message_with_different_text_is_dispatched(self, monkeypatch):
        from gateway.platforms._bluebubbles_self_chat_guard import record_sent

        adapter = _make_adapter(monkeypatch)
        handled = []

        async def fake_handle_message(event):
            handled.append(event)

        monkeypatch.setattr(adapter, "handle_message", fake_handle_message)
        record_sent("guid-we-sent", self.PHONE_GUID, "Nothing on my end. You tell me.")

        response = await adapter._handle_webhook(self._inbound("what model are you running"))
        await asyncio.sleep(0)
        assert response.status == 200
        assert len(handled) == 1

    @pytest.mark.asyncio
    async def test_same_text_in_a_different_chat_is_not_suppressed(self, monkeypatch):
        """Keyed per chat: a reply to one thread must not eat an identical
        message arriving in another."""
        from gateway.platforms._bluebubbles_self_chat_guard import record_sent

        adapter = _make_adapter(monkeypatch)
        handled = []

        async def fake_handle_message(event):
            handled.append(event)

        monkeypatch.setattr(adapter, "handle_message", fake_handle_message)
        record_sent("guid-we-sent", self.PHONE_GUID, "ok")

        response = await adapter._handle_webhook(
            self._inbound("ok", chat="iMessage;-;someoneelse@example.com")
        )
        await asyncio.sleep(0)
        assert response.status == 200
        assert len(handled) == 1

    def test_text_match_expires_after_window(self, monkeypatch):
        import gateway.platforms._bluebubbles_self_chat_guard as guard

        guard.record_sent("g", self.PHONE_GUID, "stale reply")
        assert guard.was_text_sent_recently(self.PHONE_GUID, "stale reply") is True
        real_time = guard.time.time
        monkeypatch.setattr(
            guard.time, "time", lambda: real_time() + guard._TEXT_ECHO_WINDOW_SECONDS + 1
        )
        assert guard.was_text_sent_recently(self.PHONE_GUID, "stale reply") is False

    def test_record_sent_failure_is_logged_not_silent(self, monkeypatch, caplog):
        """A swallowed write failure silently reopens the echo window; it
        must at least leave a trace."""
        import gateway.platforms._bluebubbles_self_chat_guard as guard

        def boom():
            raise RuntimeError("database is locked")

        monkeypatch.setattr(guard, "_connect", boom)
        with caplog.at_level("WARNING"):
            guard.record_sent("g", self.PHONE_GUID, "text")  # must not raise
        assert any("echo protection degraded" in r.message for r in caplog.records)


