"""Offline subprocess fixtures. Execute only in the reviewed workspace sandbox."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "bin" / "validate.py"
EXAMPLE = ROOT / "examples" / "SYNTHETIC.json"


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "bundle.json"
        self.bundle = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        # These are invented metadata, not assertions of an actual authority.
        self.source = self.bundle["sources"][0]
        self.claim = self.bundle["claims"][0]
        self.source["status"] = "verified"
        self.source["artifact_sha256"] = "a" * 64
        self.source["reviewed_at"] = "2026-01-01T00:00:00Z"
        self.source["review_ref"] = "https://example.invalid/SYNTHETIC-review"
        self.claim["status"] = "verified"

    def run_cli(self, expected, raw=None, path=None, cutoff="20260115"):
        if raw is None:
            raw = json.dumps(self.bundle).encode("utf-8")
        self.path.write_bytes(raw)
        entries = sorted(p.name for p in self.root.iterdir())
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(VALIDATOR),
                str(path or self.path),
                "--as-of",
                cutoff,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        after = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        self.assertEqual(entries, sorted(p.name for p in self.root.iterdir()))
        self.assertEqual(before, after, "validator wrote input or adjacent files")
        self.assertEqual(result.stderr, "")
        output = json.loads(result.stdout)
        self.assertEqual(
            output["verdict"], {0: "current", 3: "unverified", 4: "invalid"}[expected]
        )
        if expected != 4:
            self.assertIn("NOT legal truth", output["scope"])
        return output

    def test_current_metadata_not_truth(self):
        self.run_cli(0)

    def test_synthetic_example_unverified(self):
        self.run_cli(3, raw=EXAMPLE.read_bytes())

    def test_stale_review(self):
        self.run_cli(3, cutoff="20260202")

    def test_review_due_inclusive(self):
        self.run_cli(0, cutoff="20260201")

    def test_retrieval_day_inclusive(self):
        self.source["retrieved_at"] = "2026-01-15T23:59:59Z"
        self.source["reviewed_at"] = "2026-01-15T23:59:59Z"
        self.run_cli(0)

    def test_future_retrieval(self):
        self.source["retrieved_at"] = "2026-01-16T00:00:00Z"
        self.run_cli(4)

    def test_unverified_claim(self):
        self.claim["status"] = "unverified"
        self.run_cli(3)

    def test_verified_claim_nonverified_source(self):
        self.source["status"] = "unverified"
        self.run_cli(3)

    def test_verified_evidence_required(self):
        for key in ("quote", "artifact_sha256", "version"):
            with self.subTest(key=key):
                old = self.source[key]
                self.source[key] = ""
                self.run_cli(4)
                self.source[key] = old

    def test_digest_format(self):
        self.source["artifact_sha256"] = "xyz"
        self.run_cli(4)

    def test_unknown_fields(self):
        for record in (self.bundle, self.source, self.claim):
            with self.subTest(record=list(record)):
                record["unknown"] = True
                self.run_cli(4)
                del record["unknown"]

    def test_missing_field(self):
        del self.source["locator"]
        self.run_cli(4)

    def test_duplicate_json_key(self):
        raw = json.dumps(self.bundle).replace(
            '"publisher":', '"publisher":"x","publisher":'
        )
        self.run_cli(4, raw=raw.encode())

    def test_duplicate_ids(self):
        self.claim["id"] = self.source["id"]
        self.run_cli(4)

    def test_duplicate_source_id(self):
        self.bundle["sources"].append(copy.deepcopy(self.source))
        self.run_cli(4)

    def test_dangling_reference(self):
        self.claim["source_ids"] = ["missing"]
        self.run_cli(4)

    def test_duplicate_reference(self):
        self.claim["source_ids"] *= 2
        self.run_cli(4)

    def test_status_enums(self):
        for record in (self.source, self.claim):
            with self.subTest(record=record["id"]):
                old = record["status"]
                record["status"] = "approved"
                self.run_cli(4)
                record["status"] = old

    def test_authority_kind(self):
        self.claim["authority_kind"] = "model_vote"
        self.run_cli(4)

    def test_invalid_date(self):
        self.source["effective_from"] = "2026-02-30"
        self.run_cli(4)

    def test_noncanonical_date(self):
        self.source["review_due"] = "20260201"
        self.run_cli(4)

    def test_timestamp_requires_utc_z(self):
        self.source["retrieved_at"] = "2026-01-01T00:00:00+00:00"
        self.run_cli(4)

    def test_invalid_timestamp(self):
        self.source["retrieved_at"] = "2026-01-01T24:00:00Z"
        self.run_cli(4)

    def test_inverted_effective_range(self):
        self.source["effective_until"] = "2025-12-31"
        self.run_cli(4)

    def test_review_before_retrieval(self):
        self.source["review_due"] = "2025-12-31"
        self.run_cli(4)

    def test_effective_end_inclusive(self):
        self.source["effective_until"] = "2026-01-15"
        self.run_cli(0)
        self.source["effective_until"] = "2026-01-14"
        self.run_cli(3)

    def test_not_yet_effective(self):
        self.source["effective_from"] = "2026-01-16"
        self.run_cli(3)

    def test_supersession_cycle(self):
        self.source["status"] = self.claim["status"] = "superseded"
        self.source["superseded_by"] = self.source["id"]
        self.run_cli(4)

    def test_multi_source_cycle(self):
        other = copy.deepcopy(self.source)
        other["id"] = "other"
        self.source["status"] = other["status"] = self.claim["status"] = "superseded"
        self.source["superseded_by"] = "other"
        other["superseded_by"] = self.source["id"]
        self.bundle["sources"].append(other)
        self.run_cli(4)

    def test_dangling_supersession(self):
        self.source["status"] = self.claim["status"] = "superseded"
        self.source["superseded_by"] = "missing"
        self.run_cli(4)

    def test_unreferenced_supersession_history_is_current(self):
        old = copy.deepcopy(self.source)
        old.update(id="old", status="superseded", superseded_by=self.source["id"])
        self.bundle["sources"].append(old)
        self.run_cli(0)

    def test_link_on_verified_source(self):
        self.source["superseded_by"] = self.source["id"]
        self.run_cli(4)

    def test_empty_collections(self):
        for key in ("sources", "claims"):
            with self.subTest(key=key):
                old = self.bundle[key]
                self.bundle[key] = []
                self.run_cli(4)
                self.bundle[key] = old

    def test_wrong_types(self):
        self.source["status"] = []
        self.run_cli(4)

    def test_empty_reference_list(self):
        self.claim["source_ids"] = []
        self.run_cli(4)

    def test_uri_rejected(self):
        self.source["uri"] = "file:///etc/passwd"
        self.run_cli(4)

    def test_nul_raw_and_escaped(self):
        self.run_cli(4, raw=b"\x00")
        self.source["quote"] = "escaped\x00NUL"
        self.run_cli(4)

    def test_size_limit(self):
        self.run_cli(4, raw=b" " * 1_000_001)

    def test_size_limit_inclusive(self):
        raw = json.dumps(self.bundle).encode()
        self.run_cli(0, raw=raw + b" " * (1_000_000 - len(raw)))

    def test_malformed_json_and_encoding(self):
        for raw in (b"{", b"\xff", b'{"sources":NaN,"claims":[]}'):
            with self.subTest(raw=raw):
                self.run_cli(4, raw=raw)

    def test_symlink_input(self):
        link = self.root / "link.json"
        link.symlink_to(self.path)
        self.run_cli(4, path=link)

    def test_symlink_parent(self):
        link = self.root / "linked-dir"
        link.symlink_to(self.root, target_is_directory=True)
        self.run_cli(4, path=link / self.path.name)

    def test_symlink_followed_by_parent_traversal(self):
        target = self.root / "target"
        nested = target / "nested"
        nested.mkdir(parents=True)
        alternate = target / self.path.name
        alternate.write_bytes(b"different file reached by actual symlink traversal")
        before = alternate.read_bytes()
        link = self.root / "linked-dir"
        link.symlink_to(nested, target_is_directory=True)
        output = self.run_cli(4, path=link / ".." / self.path.name)
        self.assertIn("parent traversal", output["error"])
        self.assertEqual(alternate.read_bytes(), before)

    def test_parent_traversal_without_symlink(self):
        child = self.root / "child"
        child.mkdir()
        output = self.run_cli(4, path=child / ".." / self.path.name)
        self.assertIn("parent traversal", output["error"])

    def test_hostile_strings_are_json_data_only(self):
        marker = self.root / "must-not-be-created"
        hostile = f"SYNTHETIC\n\t\x01$(touch {marker}); `touch {marker}`"
        self.source["id"] = hostile
        self.source["quote"] = hostile
        self.source["status"] = "unverified"
        self.claim["source_ids"] = [hostile]
        output = self.run_cli(3)
        self.assertEqual(
            output["reasons"],
            [{"kind": "source", "id": hostile, "code": "unverified"}],
        )
        retained = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(retained["sources"][0]["id"], hostile)
        self.assertEqual(retained["sources"][0]["quote"], hostile)
        self.assertFalse(marker.exists())

    def test_directory_input(self):
        self.run_cli(4, path=self.root)

    def test_missing_input(self):
        self.run_cli(4, path=self.root / "missing.json")

    def test_invalid_cutoff(self):
        self.run_cli(4, cutoff="20260230")
        self.run_cli(4, cutoff="2026-01-15")

    def test_cutoff_required(self):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(VALIDATOR), str(self.path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 4)
        self.assertIn("--as-of", result.stderr)

    def test_deep_json(self):
        self.run_cli(4, raw=b"[" * 2000 + b"0" + b"]" * 2000)

    def codes(self, output):
        return {reason["code"] for reason in output["reasons"]}

    def test_schema_version_strict(self):
        for version in (True, False, 1.0, "1", 0, 2, None):
            with self.subTest(version=version):
                self.bundle["schema_version"] = version
                self.run_cli(4)

    def test_legacy_bundle_rejected(self):
        del self.bundle["schema_version"]
        del self.bundle["active_claim_ids"]
        self.run_cli(4)

    def test_active_selection(self):
        for active in (
            [],
            ["missing"],
            [self.claim["id"]] * 2,
            [self.source["id"]],
            [None],
            "synthetic-claim",
        ):
            with self.subTest(active=active):
                self.bundle["active_claim_ids"] = active
                self.run_cli(4)

    def test_selected_unknown_start(self):
        self.source["effective_from"] = None
        self.assertEqual(self.codes(self.run_cli(3)), {"unknown_effective_date"})

    def test_review_freshness_without_retrieval_change(self):
        self.source["reviewed_at"] = "2026-02-02T00:00:00Z"
        self.source["review_due"] = "2026-03-02"
        self.run_cli(0, cutoff="20260202")
        self.assertEqual(self.source["retrieved_at"], "2026-01-01T00:00:00Z")

    def test_review_required_for_verified_source(self):
        self.source["reviewed_at"] = None
        self.run_cli(4)
        self.source["reviewed_at"] = "2026-01-01T00:00:00Z"
        self.source["review_ref"] = ""
        self.run_cli(4)

    def test_review_dates(self):
        for reviewed in ("2025-12-31T00:00:00Z", "2026-01-16T00:00:00Z"):
            with self.subTest(reviewed=reviewed):
                self.source["reviewed_at"] = reviewed
                self.run_cli(4)
        self.source["reviewed_at"] = "2026-01-15T00:00:00Z"
        self.source["review_due"] = "2026-01-14"
        self.run_cli(4)

    def test_distinct_reason_codes(self):
        self.source["effective_from"] = "2026-01-16"
        self.assertEqual(self.codes(self.run_cli(3)), {"not_yet_effective"})
        self.source["effective_from"] = "2026-01-01"
        self.source["effective_until"] = "2026-01-14"
        self.assertEqual(self.codes(self.run_cli(3)), {"expired"})
        self.source["effective_until"] = None
        self.source["review_due"] = "2026-01-14"
        self.assertEqual(self.codes(self.run_cli(3)), {"review_overdue"})

    def test_retained_predecessor_selected_view(self):
        old = copy.deepcopy(self.source)
        old.update(
            id="old-source",
            status="superseded",
            superseded_by=self.source["id"],
            effective_until="2026-01-10",
        )
        old_claim = copy.deepcopy(self.claim)
        old_claim.update(id="old-claim", source_ids=["old-source"], status="superseded")
        self.bundle["sources"].append(old)
        self.bundle["claims"].append(old_claim)
        self.run_cli(0)
        self.bundle["active_claim_ids"] = ["old-claim"]
        self.assertIn("superseded", self.codes(self.run_cli(3)))

    def test_verified_claim_selected_superseded_source(self):
        self.source["status"] = "superseded"
        self.assertEqual(self.codes(self.run_cli(3)), {"superseded"})

    def test_inactive_unknown_history(self):
        history = copy.deepcopy(self.source)
        history.update(
            id="history",
            status="unverified",
            effective_from=None,
            reviewed_at=None,
            review_ref="",
            review_due="2026-01-01",
        )
        self.bundle["sources"].append(history)
        self.run_cli(0)
        history["effective_until"] = "bad-date"
        self.run_cli(4)

    def test_inactive_claim_structural_invalidity(self):
        history = copy.deepcopy(self.claim)
        history.update(id="history-claim", source_ids=["missing"], status="unverified")
        self.bundle["claims"].append(history)
        self.run_cli(4)

    def test_inactive_unverified_claim(self):
        history = copy.deepcopy(self.claim)
        history.update(id="history-claim", status="unverified")
        self.bundle["claims"].append(history)
        self.run_cli(0)
        self.bundle["active_claim_ids"] = ["history-claim"]
        output = self.run_cli(3)
        self.assertEqual(
            output["reasons"],
            [{"kind": "claim", "id": "history-claim", "code": "unverified"}],
        )

    def test_shared_source_reason_once(self):
        other = copy.deepcopy(self.claim)
        other["id"] = "other-claim"
        self.bundle["claims"].append(other)
        self.bundle["active_claim_ids"].append("other-claim")
        self.source["effective_from"] = None
        output = self.run_cli(3)
        self.assertEqual(
            output["reasons"],
            [
                {
                    "kind": "source",
                    "id": self.source["id"],
                    "code": "unknown_effective_date",
                }
            ],
        )

    def test_review_and_effective_boundaries_equal(self):
        self.source["reviewed_at"] = "2026-01-15T23:59:59Z"
        self.source["review_due"] = "2026-01-15"
        self.source["effective_from"] = "2026-01-15"
        self.source["effective_until"] = "2026-01-15"
        self.run_cli(0)

    def test_optional_publication_date(self):
        self.source["published_on"] = None
        self.run_cli(0)
        self.source["published_on"] = "2025-12-01"
        self.run_cli(0)
        self.source["published_on"] = "invalid"
        self.run_cli(4)

    def test_long_iterative_supersession_chain(self):
        for index in range(1200):
            history = copy.deepcopy(self.source)
            history.update(
                id=f"history-{index}",
                status="superseded",
                superseded_by=(
                    f"history-{index + 1}" if index < 1199 else self.source["id"]
                ),
            )
            self.bundle["sources"].append(history)
        self.assertLessEqual(len(json.dumps(self.bundle).encode()), 1_000_000)
        self.run_cli(0)
        self.bundle["sources"][-1]["superseded_by"] = "history-0"
        self.run_cli(4)


if __name__ == "__main__":
    unittest.main()
