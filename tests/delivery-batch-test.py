#!/usr/bin/env python3
"""Dependency and evidence truthfulness for human-approved PR batches."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location("batch",Path(__file__).resolve().parents[1]/"scripts/delivery-batch.py")
assert spec and spec.loader
batch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class BatchTests(unittest.TestCase):
    def manifest(self):
        return {"schema_version":1,"repo":"fixture/project","default_branch":"main","prs":[
            {"number":2,"head":"b"*40,"depends_on":[1],"review_evidence":["retained QA report"]},
            {"number":1,"head":"a"*40,"depends_on":[],"review_evidence":[]}]}

    def snapshot(self,number):
        return {"number":number,"headRefOid":("a" if number==1 else "b")*40,"baseRefOid":"c"*40,
                "reviewDecision":"REVIEW_REQUIRED","url":f"https://github.com/fixture/project/pull/{number}",
                "baseRefName":"main","headRefName":f"work-{number}","isDraft":False,"state":"OPEN",
                "statusCheckRollup":[{"__typename":"CheckRun","status":"COMPLETED","conclusion":"SUCCESS"}],"mergeCommit":None}

    def report(self,manifest=None,observations=None):
        return batch.report(manifest or self.manifest(),observations or {n:self.snapshot(n) for n in (1,2)},
                            {"nameWithOwner":"fixture/project","defaultBranchRef":{"name":"main"}})

    def test_independent_main_based_batch_green_but_no_review_authority(self):
        manifest=self.manifest(); manifest["prs"][0]["depends_on"]=[]
        result=self.report(manifest)
        self.assertEqual(result["status"],"OBSERVED")
        self.assertEqual(result["merge_order"],[1,2])
        self.assertTrue(all(not row["merge_authorized"] for row in result["prs"]))
        self.assertTrue(all(row["review_evidence_status"]=="UNVERIFIED_REFERENCES_ONLY" for row in result["prs"]))

    def test_dependent_waits_for_verified_merge_not_branch_presence(self):
        result=self.report()
        self.assertEqual(result["prs"][1]["status"],"WAITING_FOR_PREDECESSOR")
        observations={n:self.snapshot(n) for n in (1,2)}
        observations[1].update(state="MERGED",mergeCommit={"oid":"d"*40})
        result=self.report(observations=observations)
        self.assertEqual(result["prs"][0]["status"],"MERGED_OBSERVED")
        self.assertEqual(result["prs"][1]["status"],"INTEGRATION_REVIEW_REQUIRED")
        self.assertIn("UNVERIFIED",result["prs"][1]["dependency_integration"])

    def test_direct_stacking_is_flagged(self):
        observations={n:self.snapshot(n) for n in (1,2)}
        observations[2]["baseRefName"]="work-1"
        self.assertEqual(self.report(observations=observations)["prs"][1]["status"],"NONDEFAULT_BASE")

    def test_skip_absent_pending_and_failed_are_not_green(self):
        for conclusion,expected in (("SKIPPED","UNVERIFIED"),(None,"UNVERIFIED"),("FAILURE","FAILED"),("CANCELLED","FAILED")):
            check={"__typename":"CheckRun","status":"COMPLETED","conclusion":conclusion}
            self.assertEqual(batch.check_summary([check]),expected)
        self.assertEqual(batch.check_summary([]),"UNVERIFIED")
        self.assertEqual(batch.check_summary([{}]),"UNVERIFIED")
        self.assertEqual(batch.check_summary([{"__typename":"CheckRun","status":"QUEUED","conclusion":None}]),"PENDING")

    def test_changed_head_cannot_use_prior_review_refs(self):
        observations={n:self.snapshot(n) for n in (1,2)}
        observations[1]["headRefOid"]="f"*40
        result=self.report(observations=observations)
        self.assertEqual(result["prs"][0]["status"],"HEAD_CHANGED")
        self.assertEqual(result["prs"][1]["status"],"WAITING_FOR_PREDECESSOR")

    def test_cycles_unknown_and_boolean_identity_refused(self):
        for kind in ("cycle","unknown","boolean","duplicate"):
            manifest=self.manifest()
            if kind=="cycle": manifest["prs"][1]["depends_on"]=[2]
            elif kind=="unknown": manifest["prs"][0]["depends_on"]=[3]
            elif kind=="boolean": manifest["prs"][1]["number"]=True
            else: manifest["prs"].append(copy.deepcopy(manifest["prs"][0]))
            with self.subTest(kind=kind),self.assertRaises(batch.Unverified): batch.validate_manifest(manifest)

    def test_closed_dependency_and_missing_pr_stay_blocked(self):
        observations={n:self.snapshot(n) for n in (1,2)}
        observations[1]["state"]="CLOSED"
        self.assertEqual(self.report(observations=observations)["prs"][1]["status"],"WAITING_FOR_PREDECESSOR")
        self.assertEqual(self.report(observations={2:self.snapshot(2)})["prs"][0]["status"],"UNVERIFIED")

    def test_changes_requested_cannot_hide_behind_green_checks(self):
        manifest=self.manifest(); manifest["prs"][0]["depends_on"]=[]
        observations={n:self.snapshot(n) for n in (1,2)}
        observations[1]["reviewDecision"]="CHANGES_REQUESTED"
        result=self.report(manifest,observations)
        row=result["prs"][0]
        self.assertEqual(result["status"],"ATTENTION")
        self.assertEqual(row["status"],"CHANGES_REQUESTED")
        self.assertEqual(row["checks"],"GREEN_OBSERVED")
        self.assertEqual(row["url"],"https://github.com/fixture/project/pull/1")
        self.assertIn("Resolve reviewer findings",row["next_action"])
        self.assertFalse(row["merge_authorized"])

    def test_review_attention_survives_other_primary_blockers(self):
        for changed,expected in (({"isDraft":True},"DRAFT"),({"headRefOid":"f"*40},"HEAD_CHANGED"),({"baseRefName":"feature"},"NONDEFAULT_BASE")):
            snapshots={1:{**self.snapshot(1),"reviewDecision":"CHANGES_REQUESTED",**changed},2:self.snapshot(2)}
            row=self.report(observations=snapshots)["prs"][0]
            self.assertEqual(row["status"],expected)
            self.assertEqual(row["review_attention"],"CHANGES_REQUESTED")

    def test_invalid_reviews_and_urls_are_unverified(self):
        for changed in ({"reviewDecision":False},{"reviewDecision":{}},{"reviewDecision":"unknown"},
                        {"url":"https://github.com/other/project/pull/1"},{"url":"https://github.com/fixture/project/pull/2"},
                        {"url":"https://attacker.invalid/fixture/project/pull/1"}):
            row=self.report(observations={1:{**self.snapshot(1),**changed},2:self.snapshot(2)})["prs"][0]
            self.assertEqual(row["status"],"UNVERIFIED")
            self.assertNotIn("url",row)
        for decision in (None,"","APPROVED","REVIEW_REQUIRED"):
            row=self.report(observations={1:{**self.snapshot(1),"reviewDecision":decision},2:self.snapshot(2)})["prs"][0]
            self.assertEqual(row["status"],"GREEN_OBSERVED")
            self.assertFalse(row["merge_authorized"])

    def test_cli_double_reads_and_changed_snapshot_degrades(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            manifest=self.manifest(); manifest["prs"]=manifest["prs"][1:]
            path=root/"batch.json"; path.write_text(json.dumps(manifest))
            stub=root/"gh"
            stub.write_text(f'#!{sys.executable}\nimport json,sys,pathlib,os\np=pathlib.Path(os.environ["COUNT"])\nn=int(p.read_text()) if p.exists() else 0\np.write_text(str(n+1))\n' +
                'assert sys.argv[1:3] in (["repo","view"],["pr","view"])\n' +
                'v='+repr(self.snapshot(1))+'\n'+
                'if os.getenv("CHANGE") and n==2: v["headRefOid"]="f"*40\n'+
                'print(json.dumps({"nameWithOwner":"fixture/project","defaultBranchRef":{"name":"main"}} if sys.argv[1]=="repo" else v))\n')
            stub.chmod(0o700)
            env={**os.environ,"PATH":str(root)+os.pathsep+os.environ["PATH"],"COUNT":str(root/"count")}
            cmd=[sys.executable,"-I","-B",str(Path(__file__).resolve().parents[1]/"scripts/delivery-batch.py"),str(path)]
            first=subprocess.run(cmd,env=env,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            self.assertEqual((root/"count").read_text(),"3")
            (root/"count").write_text("0")
            changed=subprocess.run(cmd,env={**env,"CHANGE":"1"},capture_output=True,text=True)
            self.assertEqual(changed.returncode,3,changed.stdout+changed.stderr)
            self.assertEqual(json.loads(changed.stdout)["prs"][0]["status"],"UNVERIFIED")

    def test_invalid_manifest_never_invokes_gh(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            marker=root/"invoked"
            stub=root/"gh"
            stub.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n')
            stub.chmod(0o700)
            valid=json.dumps(self.manifest()).encode()
            for payload in (valid+b" "*100001, valid+b" "*100001+b"trailing invalid", b"["*5000+b"]"*5000):
                path=root/"batch.json"; path.write_bytes(payload)
                result=subprocess.run([sys.executable,"-I","-B",str(Path(__file__).resolve().parents[1]/"scripts/delivery-batch.py"),str(path)],
                    env={**os.environ,"PATH":str(root)+os.pathsep+os.environ["PATH"]},capture_output=True,text=True)
                self.assertEqual(result.returncode,3,result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"],"UNVERIFIED")
                self.assertNotIn("Traceback",result.stderr)
                self.assertFalse(marker.exists())

    def test_null_repository_identity_has_structured_cli_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            path=root/"batch.json"; path.write_text(json.dumps(self.manifest()))
            stub=root/"gh"
            stub.write_text(f'#!{sys.executable}\nprint(\'{{"nameWithOwner":null,"defaultBranchRef":{{"name":"main"}}}}\')\n')
            stub.chmod(0o700)
            result=subprocess.run([sys.executable,"-I","-B",str(Path(__file__).resolve().parents[1]/"scripts/delivery-batch.py"),str(path)],
                env={**os.environ,"PATH":str(root)+os.pathsep+os.environ["PATH"]},capture_output=True,text=True)
            self.assertEqual(result.returncode,3)
            self.assertEqual(json.loads(result.stdout)["status"],"UNVERIFIED")
            self.assertNotIn("Traceback",result.stderr)


if __name__=="__main__": unittest.main()
