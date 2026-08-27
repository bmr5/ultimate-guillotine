import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from openpyxl import Workbook

import scripts.dues_tracker as dues_tracker
from scripts.dues_tracker import load_tracker, update_member


class DuesTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary_directory.name)
        self.history = self.workspace / "history.xlsx"
        self.contacts = self.workspace / "league-members.json"
        self.state = self.workspace / "dues-2026.json"
        self._write_history()
        self._write_contacts()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_seed_uses_latest_roster_without_carrying_prior_paid_status(self) -> None:
        tracker = load_tracker(self.history, self.contacts, self.state, season=2026)

        self.assertEqual(tracker["season"], 2026)
        self.assertEqual(
            [member["name"] for member in tracker["members"]],
            ["Ben Ray", "Daniel Ripple", "New Person"],
        )
        self.assertEqual(
            [member["paid"] for member in tracker["members"]],
            [False, False, False],
        )
        self.assertEqual(tracker["members"][0]["email"], "ben@example.com")
        self.assertEqual(tracker["members"][0]["phone"], "5550100001")
        self.assertEqual(tracker["members"][1]["email"], "daniel@example.com")
        self.assertIsNone(tracker["members"][2]["email"])
        self.assertIsNone(tracker["members"][2]["phone"])

    def test_commissioner_is_exempt_and_not_counted_as_owing_dues(self) -> None:
        tracker = load_tracker(self.history, self.contacts, self.state, season=2026)

        ben, daniel, new_person = tracker["members"]
        self.assertFalse(ben["duesRequired"])
        self.assertEqual(ben["exemptionReason"], "Commissioner")
        self.assertTrue(daniel["duesRequired"])
        self.assertIsNone(daniel["exemptionReason"])
        self.assertTrue(new_person["duesRequired"])

    def test_exempt_commissioner_cannot_be_marked_paid(self) -> None:
        load_tracker(self.history, self.contacts, self.state, season=2026)

        with self.assertRaisesRegex(ValueError, "exempt member cannot be marked paid"):
            update_member(self.state, "ben-ray", {"paid": True})

    def test_reseed_clears_stale_payment_for_exempt_commissioner(self) -> None:
        tracker = load_tracker(self.history, self.contacts, self.state, season=2026)
        tracker["members"][0]["paid"] = True
        tracker["members"][0]["paidAt"] = "2026-08-01T12:00:00-07:00"
        self.state.write_text(json.dumps(tracker), encoding="utf-8")

        reseeded = load_tracker(self.history, self.contacts, self.state, season=2026)

        self.assertFalse(reseeded["members"][0]["paid"])
        self.assertIsNone(reseeded["members"][0]["paidAt"])

    def test_reseed_preserves_2026_payment_and_venmo_fields(self) -> None:
        load_tracker(self.history, self.contacts, self.state, season=2026)
        update_member(
            self.state,
            "daniel-ripple",
            {"paid": True, "venmoHandle": "@daniel", "notes": "Paid in August"},
            now="2026-08-27T12:00:00-07:00",
        )

        tracker = load_tracker(self.history, self.contacts, self.state, season=2026)
        daniel = tracker["members"][1]

        self.assertTrue(daniel["paid"])
        self.assertEqual(daniel["paidAt"], "2026-08-27T12:00:00-07:00")
        self.assertEqual(daniel["venmoHandle"], "daniel")
        self.assertEqual(daniel["notes"], "Paid in August")

    def test_update_rejects_unknown_member(self) -> None:
        load_tracker(self.history, self.contacts, self.state, season=2026)

        with self.assertRaisesRegex(KeyError, "unknown-member"):
            update_member(self.state, "unknown-member", {"paid": True})

    def test_update_rejects_non_boolean_paid_value(self) -> None:
        load_tracker(self.history, self.contacts, self.state, season=2026)

        with self.assertRaisesRegex(ValueError, "paid must be a boolean"):
            update_member(self.state, "ben-ray", {"paid": "yes"})

    def test_loopback_api_returns_tracker_and_persists_paid_update(self) -> None:
        self.assertTrue(
            hasattr(dues_tracker, "create_server"),
            "create_server must expose the local dues API",
        )
        server = dues_tracker.create_server(
            self.history,
            self.contacts,
            self.state,
            season=2026,
            port=0,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base_url = f"http://127.0.0.1:{server.server_port}"

        try:
            with urllib.request.urlopen(base_url) as response:
                root_status = response.status
                root_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            root_status = error.code
            root_body = error.read().decode("utf-8")

        self.assertEqual(root_status, 200)
        self.assertIn("League Dues", root_body)

        with urllib.request.urlopen(f"{base_url}/api/dues") as response:
            tracker = json.loads(response.read())

        self.assertEqual(len(tracker["members"]), 3)
        self.assertFalse(tracker["members"][0]["paid"])

        request = urllib.request.Request(
            f"{base_url}/api/members/daniel-ripple",
            data=json.dumps({"paid": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(request) as response:
            updated = json.loads(response.read())

        self.assertTrue(updated["paid"])
        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(persisted["members"][1]["paid"])

    def _write_history(self) -> None:
        workbook = Workbook()
        workbook.active.title = "Winners"
        roster = workbook.create_sheet("2025")
        roster["E1"] = "paid"
        roster.append([None, 1, "Ben", "Ray", "x"])
        roster.append([None, 2, "Daniel", "Ripple", "x"])
        roster.append([None, 3, "New", "Person", None])
        workbook.save(self.history)

    def _write_contacts(self) -> None:
        payload = {
            "source": "records.xlsx",
            "sourceSheet": "2022",
            "members": [
                {
                    "firstName": "Ben",
                    "lastName": "Ray",
                    "email": "ben@example.com",
                    "phone": "5550100001",
                },
                {
                    "firstName": "Daniel",
                    "lastName": "Ripple",
                    "email": "daniel@example.com",
                },
            ],
        }
        self.contacts.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
