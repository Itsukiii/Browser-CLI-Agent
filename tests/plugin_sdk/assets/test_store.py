from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from bca.core.errors import BCAError
from bca.plugin_sdk import assets
from bca.plugin_sdk.assets import AssetClosedError, AssetDecodeError, AssetNotFoundError, AssetStore


def test_concurrent_load_decodes_once_and_close_waits(assets_root, manifest, monkeypatch):
    from bca.plugin_sdk.assets import store as module

    value = AssetStore(assets_root)
    original = module.load_template
    entered, release, closing = Event(), Event(), Event()
    calls = []

    def decode(*args):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(module, "load_template", decode)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(value.load, "ui.confirm") for _ in range(4)]
        assert entered.wait(5)
        release.set()
        results = [future.result(timeout=5) for future in futures]
        assert all(result is results[0] for result in results) and len(calls) == 1
        value.clear_cache()
        release.clear()
        entered.clear()
        loading = pool.submit(value.load, "ui.confirm")
        assert entered.wait(5)

        def close():
            closing.set()
            value.close()

        ending = pool.submit(close)
        assert closing.wait(5) and not ending.done()
        release.set()
        saved = loading.result(timeout=5)
        ending.result(timeout=5)
    assert saved.image[0, 0].tolist() == [10, 20, 30]
    with pytest.raises(AssetClosedError):
        value.load("ui.confirm")


def test_all_operations_after_close(assets_root, manifest):
    store = AssetStore(assets_root)
    saved = store.load("ui.confirm")
    store.close()
    store.close()
    for call in (
        store.ids,
        lambda: store.variants("ui.confirm"),
        lambda: store.resolve("ui.confirm"),
        lambda: store.load("ui.confirm"),
        lambda: store.profile,
        store.cache_info,
        store.invalidate,
        store.clear_cache,
    ):
        with pytest.raises(AssetClosedError):
            call()
    assert saved.image[0, 0].tolist() == [10, 20, 30]


def test_errors_do_not_cache_partial_objects(assets_root, manifest):
    store = AssetStore(assets_root)
    with pytest.raises(AssetNotFoundError):
        store.invalidate("missing")
    (assets_root / "rgb.png").write_bytes(b"not PNG")
    for _ in range(2):
        with pytest.raises(AssetDecodeError):
            store.load("ui.confirm")
    assert store.cache_info().entries == store.cache_info().current_bytes == 0
    assert store.cache_info().misses == 2


def test_public_errors_have_unique_codes():
    errors = [getattr(assets, name) for name in assets.__all__ if name.endswith("Error")]
    assert all(issubclass(error, BCAError) for error in errors)
    assert len({error.code for error in errors}) == len(errors)
    assert all(error.code.startswith("asset.") for error in errors)
