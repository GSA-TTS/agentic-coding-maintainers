#!/usr/bin/env python3
"""Task/journal dual-write recovery without task creation or action authority."""

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parents[1] / "bin"
spec = importlib.util.spec_from_file_location("binding", BIN / "candidate-binding.py")
assert spec and spec.loader
binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(binding)
journal = binding.load("monitor-journal")


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        (self.source / "README").write_text("fixture\n")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD")
        self.git("checkout", "--detach", "-q", self.head)
        self.environment = {**os.environ,"ORCHESTRATOR_TEST_MODE":"1","ORCHESTRATOR_STATE_DIR":str(self.state)}
        created = self.command("create","review","--kind","review","--scope","fixture:binding","--repo","fixture/project",
            "--worktree",str(self.source),"--head-sha",self.head,"--base-sha",self.head,"--tracker-type","pr","--tracker-number","1")
        self.assertEqual(created.returncode,0,created.stderr)
        (self.state / "monitor").mkdir(mode=0o700)
        self.config = {"schema_version":1,"repositories":["fixture/project"],"project":None}
        self.config_path = self.root / "config.json"
        self.config_path.write_text(json.dumps(self.config))
        self.db = journal.open_store(self.state/"monitor",writable=True)
        self.addCleanup(lambda:self.db.close())
        self.poll(1)
        record = self.record()
        row = self.db.execute("SELECT * FROM events").fetchone()
        self.request = {"schema_version":1,"action":"bind-candidate","operation_id":"bind-1","task_id":"review",
            "incarnation":binding.incarnation(record),"expected_revision":record["revision"],"poll_seq":1,"config_sha256":journal.fingerprint(self.config),
            "candidate":{"store_id":self.db.execute("SELECT store_id FROM meta").fetchone()[0],"repo":"fixture/project","number":1,
                         "generation":1,"head":self.head,"fingerprint":row["fingerprint"]}}

    def git(self,*args):
        return subprocess.check_output(["git","-C",str(self.source),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
                                        "-c","commit.gpgsign=false",*args]).decode().strip()

    def command(self,*args):
        return subprocess.run([sys.executable,"-I","-B",str(BIN/"orchestrator-state.py"),*args],env=self.environment,capture_output=True,text=True)

    def record(self):
        return json.loads(self.command("show","review").stdout)

    def poll(self,number,head=None,failed=False):
        seq=journal.begin(self.db,f"poll{number}",journal.fingerprint(self.config),"monitor",["repo:fixture/project"],"start")
        item={"repo":"fixture/project","number":1,"head":head or self.head,"draft":False,"state":"OPEN","review":"APPROVED","merge":"CLEAN","checks":["SUCCESS"]}
        results={"repo:fixture/project":{"status":"UNVERIFIED" if failed else "OBSERVED","items":[] if failed else [item],"digest":None,"reason":"FETCH_FAILED" if failed else None}}
        journal.finish(self.db,seq,results,"done")

    def bind(self,request=None):
        with mock.patch.dict(os.environ,self.environment):
            return binding.bind(self.state,"review",request or self.request,self.config_path)

    def test_positive_preserves_lifecycle_and_replays_after_source_moves(self):
        before=self.record()
        result=self.bind()
        after=self.record()
        self.assertEqual(after["revision"],before["revision"]+1)
        self.assertEqual(result["result"]["status"],"CANDIDATE_BOUND")
        self.assertFalse(result["result"]["candidate_ready"])
        self.assertFalse(result["result"]["remote_authority"])
        for name in ("state","owner","worker","leases","head_sha","reviewed_sha","validation"):
            self.assertEqual(before[name],after[name])
        self.assertEqual(self.db.execute("SELECT version FROM meta").fetchone()[0],2)
        self.poll(2,head="f"*40)
        self.assertEqual(self.command("record","review","validation","unrelated evidence").returncode,0)
        saved=self.record()
        self.assertEqual(self.bind()["result"],result["result"])
        self.assertEqual(self.record(),saved)

    def test_lost_acknowledgment_repaired_without_second_task_mutation(self):
        with mock.patch.object(binding,"acknowledge",side_effect=OSError("disk unavailable")):
            first=self.bind()
        self.assertEqual(first["journal_ack"]["status"],"UNVERIFIED")
        saved=self.record()
        self.poll(2,head="f"*40)
        replay=self.bind()
        self.assertEqual(replay["result"],first["result"])
        self.assertEqual(replay["journal_ack"]["status"],"ACKNOWLEDGED")
        self.assertEqual(self.record(),saved)

    def test_crash_after_task_commit_before_ack(self):
        with mock.patch.object(binding,"acknowledge",side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): self.bind()
        saved=self.record()
        self.assertIn("candidate_binding",saved)
        result=self.bind()
        self.assertEqual(result["journal_ack"]["status"],"ACKNOWLEDGED")
        self.assertEqual(self.record(),saved)

    def test_replay_survives_missing_journal_and_config(self):
        first=self.bind()
        self.db.close()
        (self.state/"monitor/history.sqlite3").rename(self.state/"monitor/saved.sqlite3")
        self.config_path.rename(self.root/"old-config.json")
        result=self.bind()
        self.assertEqual(result["result"],first["result"])
        self.assertEqual(result["journal_ack"]["status"],"UNVERIFIED")
        self.assertFalse((self.state/"monitor/history.sqlite3").exists())

    def test_conflicting_request_and_second_binding_refused(self):
        self.bind()
        for changed in ({"operation_id":"second"},{"expected_revision":3},{"incarnation":"f"*64}):
            with self.assertRaises(binding.Refused): self.bind({**self.request,**changed})

    def test_stale_failed_out_of_scope_and_wrong_identity_refused(self):
        self.poll(2,failed=True)
        with self.assertRaises(binding.Refused): self.bind()
        with self.assertRaises(binding.Unverified): self.bind({**self.request,"poll_seq":2})
        self.poll(3)
        request={**self.request,"poll_seq":3}
        changed=copy.deepcopy(request)
        changed["candidate"]["number"]=2
        with self.assertRaises(binding.Refused): self.bind(changed)
        self.config_path.write_text(json.dumps({"schema_version":1,"repositories":["other/project"]}))
        with self.assertRaises(binding.Refused): self.bind(request)
        self.assertNotIn("candidate_binding",self.record())

    def test_corrupt_task_receipt_never_acknowledged(self):
        self.bind()
        path=self.state/"tasks/review/task.json"
        record=self.record()
        record["candidate_binding"]["result"]["candidate_ready"]=True
        path.write_text(json.dumps(record))
        self.assertEqual(self.command("show","review").returncode,3)
        with self.assertRaises(Exception): self.bind()

    def test_binding_detects_recreated_task_incarnation(self):
        self.bind()
        path=self.state/"tasks/review/task.json"
        record=self.record()
        record["created_at"]="different creation"
        path.write_text(json.dumps(record))
        self.assertEqual(self.command("show","review").returncode,3)

    def test_poll_contention_does_not_modify_unbound_task(self):
        lock=self.state/"monitor/poll.lock"
        lock.mkdir()
        before=self.record()
        with self.assertRaises(Exception): self.bind()
        self.assertEqual(before,self.record())
        lock.rmdir()
        first=self.bind()
        lock.mkdir()
        replay=self.bind()
        self.assertEqual(replay["result"],first["result"])
        self.assertEqual(replay["journal_ack"]["status"],"UNVERIFIED")

    def test_public_cli_missing_task_creates_nothing(self):
        path=self.root/"request.json"
        request={**self.request,"task_id":"absent"}
        path.write_text(json.dumps(request))
        result=subprocess.run([sys.executable,"-I","-B",str(BIN/"candidate-binding.py"),"absent","--request",str(path),"--config",str(self.config_path)],
                              env=self.environment,capture_output=True,text=True)
        self.assertEqual(result.returncode,3)
        self.assertFalse((self.state/"tasks/absent").exists())

    def test_uncertain_task_write_does_not_return_success(self):
        real_load=binding.load
        def load(name):
            module=real_load(name)
            if name=="orchestrator-state":
                actual=module.write_task
                def uncertain(root,record):
                    actual(root,record)
                    raise OSError("directory fsync uncertainty")
                module.write_task=uncertain
            return module
        with mock.patch.object(binding,"load",side_effect=load):
            with self.assertRaises(OSError): self.bind()
        saved=self.record()
        self.assertIn("candidate_binding",saved)
        self.assertEqual(self.bind()["result"],saved["candidate_binding"]["result"])
        self.assertEqual(self.record(),saved)

    def test_public_cli_one_revision_and_historical_terminal_replay(self):
        path=self.root/"request.json"
        path.write_text(json.dumps(self.request))
        args=[sys.executable,"-I","-B",str(BIN/"candidate-binding.py"),"review","--request",str(path),"--config",str(self.config_path)]
        first=subprocess.run(args,env=self.environment,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stdout+first.stderr)
        self.assertEqual(self.command("transition","review","Cancelled","--reason","fixture complete").returncode,0)
        before=(self.state/"tasks/review/task.json").read_bytes()
        replay=subprocess.run(args,env=self.environment,capture_output=True,text=True)
        self.assertEqual(replay.returncode,0,replay.stdout+replay.stderr)
        self.assertEqual(json.loads(first.stdout)["result"],json.loads(replay.stdout)["result"])
        self.assertEqual((self.state/"tasks/review/task.json").read_bytes(),before)

    def test_schema_extension_preserves_history_and_read_only_status(self):
        history=[tuple(row) for row in self.db.execute("SELECT * FROM events")]
        self.bind()
        self.assertEqual(history,[tuple(row) for row in self.db.execute("SELECT * FROM events")])
        path=self.state/"monitor/history.sqlite3"
        before=path.read_bytes()
        reader=journal.open_store(self.state/"monitor")
        try:
            status=journal.status(reader,["repo:fixture/project"])
            self.assertEqual(status["candidates"][0]["admission"],"UNMEASURED")
        finally:
            reader.close()
        self.assertEqual(path.read_bytes(),before)

    def test_store_replacement_does_not_acknowledge_old_binding(self):
        first=self.bind()
        self.db.execute("UPDATE meta SET store_id=?",("f"*32,))
        self.db.commit()
        result=self.bind()
        self.assertEqual(result["result"],first["result"])
        self.assertEqual(result["journal_ack"]["status"],"UNVERIFIED")

    def test_fixed_review_head_corruption_refused(self):
        self.bind()
        record=self.record()
        record["head_sha"]="f"*40
        (self.state/"tasks/review/task.json").write_text(json.dumps(record))
        self.assertEqual(self.command("show","review").returncode,3)
        with self.assertRaises(Exception): self.bind()

    def test_fsync_barrier_precedes_contended_replay(self):
        self.bind()
        (self.state/"monitor/poll.lock").mkdir()
        with mock.patch.object(binding,"durable_receipt",side_effect=OSError("uncertain durability")) as barrier:
            with self.assertRaises(OSError): self.bind()
            self.assertEqual(barrier.call_count,1)
        result=self.bind()
        self.assertEqual(result["result"]["status"],"CANDIDATE_BOUND")
        self.assertEqual(result["journal_ack"]["status"],"UNVERIFIED")

    def test_corruption_between_lookups_never_returns_cached_success(self):
        self.bind()
        real_load=binding.load
        def load(name):
            module=real_load(name)
            if name=="orchestrator-monitor":
                acquire=module.acquire
                def corrupt(path):
                    acquire(path)
                    (self.state/"tasks/review/task.json").write_text('{}')
                module.acquire=corrupt
            return module
        with mock.patch.object(binding,"load",side_effect=load):
            with self.assertRaises(Exception): self.bind()

    def test_orphan_acknowledgment_cannot_recreate_task_receipt(self):
        self.bind()
        record=self.record()
        del record["candidate_binding"]
        path=self.state/"tasks/review/task.json"
        path.write_text(json.dumps(record))
        request={**self.request,"expected_revision":record["revision"]}
        before=path.read_bytes()
        with self.assertRaisesRegex(binding.Unverified,"receipt is missing"):
            self.bind(request)
        self.assertEqual(path.read_bytes(),before)

    def test_failed_schema_extension_rolls_back_preserving_task(self):
        with mock.patch.object(binding,"acknowledge",side_effect=OSError("ack delayed")):
            self.bind()
        record=self.record()
        self.assertEqual(self.db.execute("SELECT version FROM meta").fetchone()[0],1)
        def deny_meta_update(action,table,column,database,trigger):
            if action==journal.sqlite3.SQLITE_UPDATE and table=="meta":
                return journal.sqlite3.SQLITE_DENY
            return journal.sqlite3.SQLITE_OK
        self.db.set_authorizer(deny_meta_update)
        try:
            with self.assertRaises(Exception):
                binding.acknowledge(self.db,record["candidate_binding"])
        finally:
            self.db.set_authorizer(None)
        self.assertEqual(self.db.execute("SELECT version FROM meta").fetchone()[0],1)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='binding_acks'").fetchone())
        self.assertEqual(self.record(),record)
        self.assertEqual(self.bind()["journal_ack"]["status"],"ACKNOWLEDGED")


if __name__=="__main__":
    unittest.main()
