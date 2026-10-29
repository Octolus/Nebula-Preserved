"""Configured success/atomicity cases with audited immutable fixture state."""
import json
from common import HERE, write_json
from fixture_support import account_guid


def corpus():
    a, b = "fixture-parity-a", "fixture-parity-b"
    ga, gb = account_guid(a, "d" * 64), account_guid(b, "e" * 64)
    housing = json.loads((HERE / "fixtures/housing-parts.json").read_text())
    parts = housing["parts"]
    cases = []
    def call(label, route, *fields, status=200, expect=None, category="configured_success"):
        row = {"id": label, "op": "http", "route": route, "plaintext": "#".join(fields) + "#StandaloneWindows",
               "method": "GET", "expected_status": status, "category": category}
        if expect is not None:
            row["expected_plaintext"] = expect
        cases.append(row)
    def snap(label, same_as=None):
        row = {"id": label, "op": "snapshot", "category": "typed_durable_state"}
        if same_as:
            row["reference_same_state_as"] = same_as
        cases.append(row)
    def buy(label, offer, crystals, np, option="0", **kwargs):
        call(label, "NPShopBuyItemServlet", ga, a, offer, str(crystals), str(np), option, **kwargs)
    snap("fixture-initial")
    call("fixture-wallet-initial-a", "GetShopInfoPlayerShop", ga, a, expect="true#" + ga + "#" + a + "#Fixture A#40#150")
    call("fixture-wallet-initial-b", "GetShopInfoPlayerShop", gb, b, expect="true#" + gb + "#" + b + "#Fixture B#1#3")
    call("fixture-shop-catalog", "GetShopDataShopServlet", ga, a, "false", "false", "0")
    call("fixture-shop-features", "GetFeaturesServlet", ga, a)
    call("fixture-shop-genders", "GetGenderDataShopServlet", ga, a, "fixture-shop")
    call("fixture-shop-types", "GetShopTypeDataShopServlet", ga, a, "fixture-shop", "0")
    call("fixture-shop-items", "GetItemAssetsDataServlet", ga, a, "fixture-shop", "0", "companions")
    call("fixture-shop-bundle-items", "NPShopBundleItemsServlet", ga, a, "fixture-bundle-buy")
    buy("fixture-buy-price-denied", "fixture-pet-buy", 19, 7, status=409, category="atomicity")
    snap("fixture-after-wrong-price", "fixture-initial")
    buy("fixture-buy-success", "fixture-pet-buy", 20, 7, expect="true#" + ga + "#" + a + "#OK")
    snap("fixture-after-buy")
    buy("fixture-buy-idempotent", "fixture-pet-buy", 20, 7, expect="true#" + ga + "#" + a + "#ISPURCHASED", category="idempotence")
    snap("fixture-after-buy-duplicate", "fixture-after-buy")
    call("fixture-owned-after-buy", "NPShopIsItemPurchasedServlet", ga, a, "fixture-pet-buy", expect="true#" + ga + "#" + a + "#True")
    call("fixture-wallet-after-buy", "GetShopInfoPlayerShop", ga, a, expect="true#" + ga + "#" + a + "#Fixture A#40#130")
    buy("fixture-bundle-success", "fixture-bundle-buy", 25, 6, expect="true#" + ga + "#" + a + "#OK")
    snap("fixture-after-bundle")
    buy("fixture-bundle-idempotent", "fixture-bundle-buy", 25, 6, expect="true#" + ga + "#" + a + "#ISPURCHASED", category="idempotence")
    snap("fixture-after-bundle-duplicate", "fixture-after-bundle")
    buy("fixture-bundle-midgrant-rollback", "fixture-bundle-rollback", 10, 6, status=404, category="atomicity")
    snap("fixture-after-bundle-rollback", "fixture-after-bundle")
    call("fixture-wallet-after-rollback", "GetShopInfoPlayerShop", ga, a, expect="true#" + ga + "#" + a + "#Fixture A#40#105")
    call("fixture-gift-price-denied", "NPShopGiftItemServlet", ga, a, "fixture-pet-gift", "Fixture B", "14", status=409, category="atomicity")
    snap("fixture-after-gift-wrong-price", "fixture-after-bundle")
    call("fixture-gift-success", "NPShopGiftItemServlet", ga, a, "fixture-pet-gift", "Fixture B", "15", expect="true#" + ga + "#" + a + "#OK#Fixture B#fixture-pet-gift")
    snap("fixture-after-gift")
    call("fixture-gift-idempotent", "NPShopGiftItemServlet", ga, a, "fixture-pet-gift", "Fixture B", "15", expect="true#" + ga + "#" + a + "#ISPURCHASED#Fixture B#fixture-pet-gift", category="idempotence")
    snap("fixture-after-gift-duplicate", "fixture-after-gift")
    call("fixture-wallet-after-gift", "GetShopInfoPlayerShop", ga, a, expect="true#" + ga + "#" + a + "#Fixture A#40#90")
    call("fixture-block-friend", "N2AddBlock", ga, "Fixture B", "1", category="authority")
    call("fixture-blocked-gift-denied", "NPShopGiftItemServlet", ga, a, "fixture-pet-gift", "Fixture B", "15", status=403, category="authority")
    call("fixture-unblock-friend", "N2RemoveBlock", ga, "Fixture B", "1", category="authority")
    snap("fixture-after-block-cycle", "fixture-after-gift")
    call("fixture-reward-unowned", "CheckOwnGenericReward", ga, a, "fixture-generic", expect="false#" + ga + "#" + a + "#false")
    call("fixture-reward-claim", "GenericReward", ga, a, "fixture-generic", expect="false#" + ga + "#" + a + "#true")
    snap("fixture-after-generic-reward")
    call("fixture-reward-duplicate", "GenericReward", ga, a, "fixture-generic", expect="false#" + ga + "#" + a + "#false", category="idempotence")
    snap("fixture-after-generic-duplicate", "fixture-after-generic-reward")
    call("fixture-reward-owned", "CheckOwnGenericReward", ga, a, "fixture-generic", expect="false#" + ga + "#" + a + "#true")
    call("fixture-coffee-reward", "RewardConsumeServlet", ga, a, "fixture-coffee", expect="true#" + ga + "#" + a)
    snap("fixture-after-coffee-reward")
    call("fixture-coffee-reward-duplicate", "RewardConsumeServlet", ga, a, "fixture-coffee", expect="true#" + ga + "#" + a, category="idempotence")
    snap("fixture-after-coffee-duplicate", "fixture-after-coffee-reward")
    call("fixture-coffee-balance", "GetConsumablePriceServlet", ga, a, "coffee", "0", expect="true#" + ga + "#" + a + "#coffee##1#local token#2#false")
    call("fixture-coffee-other-account", "GetConsumablePriceServlet", gb, b, "coffee", "0", expect="true#" + gb + "#" + b + "#coffee##1#local token#0#false", category="isolation")
    call("fixture-locomotion-reward", "RewardConsumeServlet", ga, a, "fixture-locomotion")
    call("fixture-cinema-capability", "CinemaInteractionNPServlet", ga, a, "0")
    snap("fixture-after-cinema")
    call("fixture-cinema-idempotent", "CinemaInteractionNPServlet", ga, a, "0", category="idempotence")
    snap("fixture-after-cinema-duplicate", "fixture-after-cinema")
    for label, guid, account in [("a", ga, a), ("b", gb, b)]:
        call("fixture-companions-" + label, "GetCompanionsServlet", guid, account, category="isolation")
        call("fixture-locomotions-" + label, "GetLocomotionsServlet", guid, account, category="isolation")
        call("fixture-purchases-" + label, "GetPurchases", guid, category="isolation")
    call("fixture-housing-owner-load-empty", "HousingReadPresetServlet", ga, a, "Home")
    call("fixture-housing-visitor-write-denied", "HousingSavePresetServletParts", gb, b, parts[1], "1", status=403, category="authority")
    call("fixture-housing-part0-duplicate", "HousingSavePresetServletParts", ga, a, parts[0], "0", category="idempotence")
    snap("fixture-before-partial-reopen")
    cases.append({"id": "fixture-partial-process-reopen", "op": "process_restart", "category": "persistence"})
    snap("fixture-after-partial-reopen", "fixture-before-partial-reopen")
    call("fixture-housing-part1-commit", "HousingSavePresetServletParts", ga, a, parts[1], "1")
    snap("fixture-after-whole-commit")
    call("fixture-housing-read-committed", "HousingReadPresetServlet", ga, a, "Home")
    call("fixture-housing-part1-idempotent", "HousingSavePresetServletParts", ga, a, parts[1], "1", category="idempotence")
    snap("fixture-after-housing-duplicate", "fixture-after-whole-commit")
    call("fixture-housing-visitor-read-absent-owner", "HousingReadPresetServlet", gb, b, "Home", status=503, category="authority")
    snap("fixture-before-complete-reopen", "fixture-after-whole-commit")
    cases.append({"id": "fixture-complete-process-reopen", "op": "process_restart", "category": "persistence"})
    snap("fixture-after-complete-reopen", "fixture-before-complete-reopen")
    call("fixture-housing-after-process-reopen", "HousingReadPresetServlet", ga, a, "Home", category="persistence")
    call("fixture-wallet-after-process-reopen", "GetShopInfoPlayerShop", ga, a, expect="true#" + ga + "#" + a + "#Fixture A#40#90", category="persistence")
    call("fixture-reward-after-process-reopen", "CheckOwnGenericReward", ga, a, "fixture-generic", expect="false#" + ga + "#" + a + "#true", category="persistence")
    return cases


if __name__ == "__main__":
    cases = corpus()
    write_json(HERE / "fixtures/configured-corpus.json", cases)
    print(json.dumps({"configured_cases": len(cases)}))
