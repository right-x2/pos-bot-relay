import unittest
from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "rag_relay_server.ps1").read_text()


class RagRelayRouteTests(unittest.TestCase):
    def test_store_access_is_explicitly_routed_before_chat(self):
        store_route = 'elseif ($Path -eq "/tools/store_access")'
        chat_route = 'elseif (($Path -eq "/test") -or ($Path -eq "/api/rag/chat"))'
        self.assertIn(store_route, SCRIPT)
        self.assertIn(chat_route, SCRIPT)
        self.assertLess(SCRIPT.index(store_route), SCRIPT.index(chat_route))
        self.assertIn('$TargetUrl = $StoreAccessUrl', SCRIPT)

    def test_item_name_search_preserves_multipart_route(self):
        self.assertIn(
            '$ItemNameSearchUrl = "http://10.103.201.164:8000/api/items/search-by-name"',
            SCRIPT,
        )
        self.assertIn('($Path -eq "/api/items/search-by-name")', SCRIPT)
        self.assertIn('$BinaryTargetUrl = $ItemNameSearchUrl', SCRIPT)
        self.assertIn('$BinaryResult = Invoke-BinaryPost', SCRIPT)

    def test_startup_identifies_the_running_script(self):
        self.assertIn('Write-Host "Script   : $($MyInvocation.MyCommand.Path)"', SCRIPT)
        self.assertIn('Write-Host "Version  : $RelayVersion"', SCRIPT)
        self.assertIn('Write-Host "Store    : $StoreAccessUrl"', SCRIPT)

    def test_hpoint_event_lookup_is_explicitly_routed(self):
        self.assertIn(
            '$HpointEventLookupUrl = "http://10.103.201.164:8000/tools/hpoint_event_lookup"',
            SCRIPT,
        )
        route = 'elseif ($Path -eq "/tools/hpoint_event_lookup")'
        chat_route = 'elseif (($Path -eq "/test") -or ($Path -eq "/api/rag/chat"))'
        self.assertIn(route, SCRIPT)
        self.assertIn('$TargetUrl = $HpointEventLookupUrl', SCRIPT)
        self.assertLess(SCRIPT.index(route), SCRIPT.index(chat_route))


if __name__ == "__main__":
    unittest.main()
