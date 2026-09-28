import os
import unittest
from unittest.mock import MagicMock, patch
from config import parse_login, parse_str_credential, settings
from models import PairConfig, PairMode
from mt5_bridge import MT5Bridge

class TestMT5Login(unittest.TestCase):
    def test_parse_login_helper(self):
        """Verify parse_login returns integers for valid account IDs and None for blank/invalid."""
        self.assertIsNone(parse_login(None))
        self.assertIsNone(parse_login(""))
        self.assertIsNone(parse_login("   "))
        self.assertIsNone(parse_login(0))
        self.assertIsNone(parse_login("0"))
        self.assertIsNone(parse_login(-123))
        self.assertIsNone(parse_login("invalid"))
        self.assertIsNone(parse_login("123abc"))
        
        self.assertEqual(parse_login(12345678), 12345678)
        self.assertEqual(parse_login("12345678"), 12345678)
        self.assertEqual(parse_login("  87654321  "), 87654321)

    def test_parse_str_credential_helper(self):
        """Verify parse_str_credential trims strings and returns None for empty/blank."""
        self.assertIsNone(parse_str_credential(None))
        self.assertIsNone(parse_str_credential(""))
        self.assertIsNone(parse_str_credential("   "))
        
        self.assertEqual(parse_str_credential("my_password"), "my_password")
        self.assertEqual(parse_str_credential("  Server-Name  "), "Server-Name")

    def test_pair_env_credentials_parsing(self):
        """Verify PAIR_{i}_MT5_LOGIN, PASSWORD, SERVER are correctly parsed from environment."""
        env_updates = {
            "PAIR_1_MT5_LOGIN": "123456",
            "PAIR_1_MT5_PASSWORD": "secret_password",
            "PAIR_1_MT5_SERVER": "MetaQuotes-Demo",
            "PAIR_2_MT5_LOGIN": "",  # explicitly blank
            "PAIR_2_MT5_PASSWORD": "",
            "PAIR_2_MT5_SERVER": "",
        }
        old_env = {k: os.environ.get(k) for k in env_updates}
        try:
            os.environ.update(env_updates)
            pairs = settings.get_configured_pairs()
            
            p1 = next((p for p in pairs if p.id == 1), None)
            self.assertIsNotNone(p1)
            self.assertEqual(p1.mt5_login, 123456)
            self.assertEqual(p1.mt5_password, "secret_password")
            self.assertEqual(p1.mt5_server, "MetaQuotes-Demo")

            p2 = next((p for p in pairs if p.id == 2), None)
            self.assertIsNotNone(p2)
            self.assertIsNone(p2.mt5_login, "Blank login should result in None")
            self.assertIsNone(p2.mt5_password, "Blank password should result in None")
            self.assertIsNone(p2.mt5_server, "Blank server should result in None")
        finally:
            for k, old_val in old_env.items():
                if old_val is not None:
                    os.environ[k] = old_val
                else:
                    os.environ.pop(k, None)

    def test_pair_alias_credentials_parsing(self):
        """Verify legacy aliases PAIR_{i}_LOGIN, PAIR_{i}_PASSWORD, PAIR_{i}_SERVER work."""
        env_updates = {
            "PAIR_1_MT5_LOGIN": "",  # clear primary
            "PAIR_1_LOGIN": "987654",
            "PAIR_1_PASSWORD": "alias_pass",
            "PAIR_1_SERVER": "Broker-Real",
        }
        old_env = {k: os.environ.get(k) for k in env_updates}
        try:
            # Remove any PAIR_1_MT5_* that might take precedence
            os.environ.pop("PAIR_1_MT5_LOGIN", None)
            os.environ.pop("PAIR_1_MT5_PASSWORD", None)
            os.environ.pop("PAIR_1_MT5_SERVER", None)
            os.environ.update(env_updates)
            
            pairs = settings.get_configured_pairs()
            p1 = next((p for p in pairs if p.id == 1), None)
            self.assertIsNotNone(p1)
            self.assertEqual(p1.mt5_login, 987654)
            self.assertEqual(p1.mt5_password, "alias_pass")
            self.assertEqual(p1.mt5_server, "Broker-Real")
        finally:
            for k, old_val in old_env.items():
                if old_val is not None:
                    os.environ[k] = old_val
                else:
                    os.environ.pop(k, None)

    def test_json_pairs_credentials_parsing(self):
        """Verify credentials in PAIRS JSON array are parsed."""
        raw_json = (
            '[{"name": "JSON-P1", "channel": "-1001", "mt5_path": "C:\\\\mt5\\\\terminal64.exe", '
            '"mt5_login": 555666, "mt5_password": "json_pass", "mt5_server": "Demo-Server"}, '
            '{"name": "JSON-P2", "channel": "-1002", "mt5_path": "C:\\\\mt5\\\\terminal64.exe", '
            '"login": "", "password": ""}]'
        )
        old_pairs = os.environ.get("PAIRS")
        try:
            os.environ["PAIRS"] = raw_json
            pairs = settings.get_configured_pairs()
            self.assertEqual(len(pairs), 2)
            
            self.assertEqual(pairs[0].mt5_login, 555666)
            self.assertEqual(pairs[0].mt5_password, "json_pass")
            self.assertEqual(pairs[0].mt5_server, "Demo-Server")

            self.assertIsNone(pairs[1].mt5_login)
            self.assertIsNone(pairs[1].mt5_password)
            self.assertIsNone(pairs[1].mt5_server)
        finally:
            if old_pairs is not None:
                os.environ["PAIRS"] = old_pairs
            else:
                os.environ.pop("PAIRS", None)

    def test_connect_blank_credentials_uses_existing_session(self):
        """When login is blank/None, MT5Bridge connects without calling mt5.login."""
        pair = PairConfig(
            id=1,
            name="Blank-Login-Pair",
            channel="-1001",
            mt5_path="C:\\mock\\terminal64.exe",
            mt5_login=None,
            mt5_password=None,
            mt5_server=None,
        )
        bridge = MT5Bridge(pair_config=pair)

        with patch("os.path.exists", return_value=True), \
             patch("mt5_bridge.mt5") as mock_mt5:
            mock_mt5.initialize.return_value = True
            mock_term = MagicMock()
            mock_term.name = "MetaTrader 5"
            mock_term.path = "C:\\mock\\terminal64.exe"
            mock_term.trade_allowed = True
            mock_mt5.terminal_info.return_value = mock_term

            mock_acc = MagicMock()
            mock_acc.login = 111222
            mock_acc.server = "Existing-Server"
            mock_acc.balance = 50.0
            mock_acc.equity = 50.0
            mock_acc.leverage = 100
            mock_acc.currency = "USD"
            mock_mt5.account_info.return_value = mock_acc

            ok = bridge.connect()
            self.assertTrue(ok)
            self.assertTrue(bridge.connected)
            mock_mt5.initialize.assert_called_once_with(path="C:\\mock\\terminal64.exe")
            mock_mt5.login.assert_not_called()

    def test_connect_with_login_already_logged_in_skips_login(self):
        """When terminal is already logged into the requested account & server, skip calling mt5.login."""
        pair = PairConfig(
            id=1,
            name="Already-Logged-Pair",
            channel="-1001",
            mt5_path="C:\\mock\\terminal64.exe",
            mt5_login=12345,
            mt5_password="mypassword",
            mt5_server="Demo-Server",
        )
        bridge = MT5Bridge(pair_config=pair)

        with patch("os.path.exists", return_value=True), \
             patch("mt5_bridge.mt5") as mock_mt5:
            mock_mt5.initialize.return_value = True
            mock_term = MagicMock()
            mock_term.trade_allowed = True
            mock_mt5.terminal_info.return_value = mock_term

            # Account info already matches requested login and server
            mock_acc = MagicMock()
            mock_acc.login = 12345
            mock_acc.server = "Demo-Server"
            mock_acc.balance = 100.0
            mock_acc.equity = 100.0
            mock_acc.leverage = 500
            mock_acc.currency = "USD"
            mock_mt5.account_info.return_value = mock_acc

            ok = bridge.connect()
            self.assertTrue(ok)
            self.assertTrue(bridge.connected)
            mock_mt5.initialize.assert_called_once_with(path="C:\\mock\\terminal64.exe")
            mock_mt5.login.assert_not_called()

    def test_connect_with_credentials_performs_login(self):
        """When requested login differs from current terminal session, mt5.login is called."""
        pair = PairConfig(
            id=1,
            name="New-Login-Pair",
            channel="-1001",
            mt5_path="C:\\mock\\terminal64.exe",
            mt5_login=998877,
            mt5_password="secure_password",
            mt5_server="Live-Server",
        )
        bridge = MT5Bridge(pair_config=pair)

        with patch("os.path.exists", return_value=True), \
             patch("mt5_bridge.mt5") as mock_mt5:
            mock_mt5.initialize.return_value = True
            mock_term = MagicMock()
            mock_term.trade_allowed = True
            mock_mt5.terminal_info.return_value = mock_term

            # Initially logged into another account (or None)
            initial_acc = MagicMock()
            initial_acc.login = 111111
            initial_acc.server = "Other-Server"

            logged_acc = MagicMock()
            logged_acc.login = 998877
            logged_acc.server = "Live-Server"
            logged_acc.balance = 250.0
            logged_acc.equity = 250.0
            logged_acc.leverage = 200
            logged_acc.currency = "USD"

            state = {"logged_in": False}
            def fake_login(**kwargs):
                state["logged_in"] = True
                return True
            mock_mt5.login.side_effect = fake_login
            mock_mt5.account_info.side_effect = lambda: logged_acc if state["logged_in"] else initial_acc

            ok = bridge.connect()
            self.assertTrue(ok)
            self.assertTrue(bridge.connected)
            mock_mt5.login.assert_called_once_with(
                login=998877,
                password="secure_password",
                server="Live-Server"
            )

    def test_connect_login_failure(self):
        """When mt5.login fails, connect() returns False and self.connected is False."""
        pair = PairConfig(
            id=1,
            name="Failed-Login-Pair",
            channel="-1001",
            mt5_path="C:\\mock\\terminal64.exe",
            mt5_login=998877,
            mt5_password="wrong_password",
            mt5_server="Live-Server",
        )
        bridge = MT5Bridge(pair_config=pair)

        with patch("os.path.exists", return_value=True), \
             patch("mt5_bridge.mt5") as mock_mt5:
            mock_mt5.initialize.return_value = True
            mock_term = MagicMock()
            mock_term.trade_allowed = True
            mock_mt5.terminal_info.return_value = mock_term

            mock_mt5.account_info.return_value = None
            mock_mt5.login.return_value = False
            mock_mt5.last_error.return_value = (-1, "Invalid account/password")

            ok = bridge.connect()
            self.assertFalse(ok)
            self.assertFalse(bridge.connected)
            mock_mt5.login.assert_called_once_with(
                login=998877,
                password="wrong_password",
                server="Live-Server"
            )

    def test_connect_initialize_failure(self):
        """When terminal path does not exist or initialize fails, connect returns False."""
        pair = PairConfig(
            id=1,
            name="Invalid-Path-Pair",
            channel="-1001",
            mt5_path="C:\\nonexistent\\terminal64.exe",
        )
        bridge = MT5Bridge(pair_config=pair)
        self.assertFalse(bridge.connect())
        self.assertFalse(bridge.connected)

if __name__ == "__main__":
    unittest.main()
