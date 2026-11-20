"""Endpoint ceilings follow the inference route, not the model slug or loopback address."""

from agent.context_compressor import ContextCompressor


LOCAL = "http://127.0.0.1:8001/v1"
PROXY = "http://127.0.0.1:8788/v1"
CLOUD = "https://example.com/v1"


def test_endpoint_ceiling_tracks_route_and_preserves_window_safety():
    for window, reservation, cloud_trigger, local_trigger in (
        (1_000_000, 32_768, 483_616, 120_000),
        (131_072, 32_768, 73_728, 73_728),
        (65_536, 32_768, 27_852, 27_852),
    ):
        cc = ContextCompressor(
            model="same-model", provider="custom", base_url=CLOUD,
            config_context_length=window, max_tokens=reservation,
            threshold_tokens_cap=None, endpoint_threshold_tokens={LOCAL: 120_000},
            quiet_mode=True,
        )
        assert cc.threshold_tokens == cloud_trigger
        for destination, expected in ((LOCAL + "/", local_trigger), (PROXY, cloud_trigger), (CLOUD, cloud_trigger)):
            preview = cc.preview_threshold_tokens("same-model", window, "custom", base_url=destination)
            assert cc.threshold_tokens == cloud_trigger  # Preview must not mutate the active route.
            cc.update_model("same-model", window, base_url=destination, provider="custom")
            assert cc.threshold_tokens == preview == expected
            cc.update_model("same-model", window, base_url=CLOUD, provider="custom")
        cc.threshold_tokens_cap = 90_000
        cc.update_model("same-model", window, base_url=LOCAL, provider="custom")
        assert cc.threshold_tokens == min(90_000, local_trigger)
