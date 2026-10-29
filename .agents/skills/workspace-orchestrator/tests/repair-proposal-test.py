#!/usr/bin/env python3
"""Proposal admission, exact rendering, role/context substitution and replay."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

ROOT=Path(__file__).resolve().parents[1]
fixture=load(Path(__file__).with_name("repair-apply-test.py"),"repair_fixture")
p=load(ROOT/"bin/repair-proposal.py","proposal")
c=p.load("review-collect")

class ProposalTests(fixture.RepairTests):
    def admit_proposal(self):
        request=dict(schema_version=1,operation_id="propose",expected_revision=self.record["revision"],action="admit",payload=dict(
            correction_id=self.correction_id,session="ses_owner",model="fixture/model",agent="owner",binary_sha256="a"*64,
            profile_sha256="b"*64,cwd="/review",sources={"/candidate/source.py":"source.py"}))
        self.record,result,_=p.apply(self.record,request,self.state); self.record["revision"]+=1
        return request,result

    def artifacts(self, admitted, content=None):
        final=json.dumps(content or dict(schema_version=1,status="proposed",replacements=[dict(path="source.py",content="result = 2\n")],limitations=[]))
        events=[dict(type="tool_use",sessionID="ses_owner",part=dict(tool="read",state=dict(status="completed",input=dict(path="/candidate/source.py"),output="Read file /candidate/source.py, lines 1-1\n1: result = 1"))),
                dict(type="text",sessionID="ses_owner",part=dict(text=final)),dict(type="step_finish",sessionID="ses_owner",part=dict(reason="stop",tokens=dict(input=100,output=50)))]
        transcript=b"".join(c.canonical(event) for event in events)
        exported=c.canonical(dict(info=dict(id="ses_owner",outcome="succeeded",agent="owner",model=dict(providerID="fixture",id="model"),tokens=dict(input=100,output=50)),messages=[dict(type="assistant",finish="stop",content=[dict(type="text",text=final)])]))
        receipt={name:admitted[name] for name in ("model","agent","binary_sha256","profile_sha256","source_sha256")}
        receipt.update(role="owner-proposal",context_sha256=c.digest(c.canonical(admitted["context"])),sessions=["ses_owner"],status="REVIEW_OBSERVED",candidate_ready=False,execution_credit=False,
            transcript_sha256=c.digest(transcript),stderr_sha256=c.digest(b""),returncode=0,export_returncode=0,export_failure=None,final_text=final)
        return {"receipt.json":c.canonical(receipt),"transcript.jsonl":transcript,"session-export.json":exported,"stderr.txt":b"","export-stderr.txt":b""}

    def test_model_proposal_collected_and_applied_without_editing_content(self):
        request,result=self.admit_proposal(); admission_id=result["admission_id"]
        before=copy.deepcopy(self.record)
        _,replay,changed=p.apply(self.record,request,self.state)
        self.assertFalse(changed); self.assertEqual(replay,result); self.assertEqual(before,self.record)
        admitted=self.record["repair_proposals"][admission_id]["admission"]
        artifacts=self.artifacts(admitted)
        collect=dict(schema_version=1,operation_id="collect-proposal",expected_revision=self.record["revision"],action="collect",payload=dict(admission_id=admission_id,artifact_sha256={name:c.digest(data) for name,data in artifacts.items()}))
        self.record,result,_=p.apply(self.record,collect,self.state,artifacts); self.record["revision"]+=1
        self.assertEqual(result["status"],"PROPOSAL_COLLECTED")
        raw=(self.state/"review-artifacts"/result["bundle_sha256"]).read_bytes()
        apply_request=dict(schema_version=1,operation_id="apply-proposal",expected_revision=self.record["revision"],correction_id=self.correction_id,bundle_sha256=result["bundle_sha256"])
        fixture.repair.apply_repair(self.record,self.state,apply_request,raw,self.persist)
        self.assertEqual((self.repo/"source.py").read_text(),"result = 2\n")
        _,replay,changed=p.apply(self.record,collect,self.state)
        self.assertFalse(changed); self.assertEqual(replay,result)

    def test_unable_is_not_repair(self):
        _,result=self.admit_proposal(); admitted=self.record["repair_proposals"][result["admission_id"]]["admission"]
        artifacts=self.artifacts(admitted,dict(schema_version=1,status="unable",replacements=[],limitations=["insufficient source"]))
        self.assertIsNone(p.verify_artifacts(admitted,artifacts,c,p.load("review-run"),fixture.repair))

    def test_context_role_and_scope_substitution_refused(self):
        _,result=self.admit_proposal(); admitted=self.record["repair_proposals"][result["admission_id"]]["admission"]
        for field,value in (("context_sha256","0"*64),("role","review"),("sessions",["ses_other"])):
            artifacts=self.artifacts(admitted); receipt=c.decode(artifacts["receipt.json"]); receipt[field]=value; artifacts["receipt.json"]=c.canonical(receipt)
            with self.subTest(field=field),self.assertRaises(ValueError): p.verify_artifacts(admitted,artifacts,c,p.load("review-run"),fixture.repair)
        output=dict(schema_version=1,status="proposed",replacements=[dict(path="test.py",content="changed")],limitations=[])
        with self.assertRaises(ValueError): p.render(json.dumps(output),admitted,fixture.repair,c)

    def test_prepared_correction_blocks_accidental_new_generation(self):
        generation=self.record["review_protocol"]["generations"][-1]
        request=dict(schema_version=1,operation_id="wrong-begin",expected_revision=self.record["revision"],action="begin",
            payload={name:generation[name] for name in ("packet","policy","base","head","obligations")})
        with self.assertRaisesRegex(Exception,"prepared repair must"): fixture.e.apply(self.record,request)

    def test_owner_and_reviewer_session_overlap_refused(self):
        request,result=self.admit_proposal()
        before=copy.deepcopy(self.record)
        attempted=copy.deepcopy(request)
        attempted.update(operation_id="second",expected_revision=self.record["revision"])
        attempted["payload"]["session"]="ses_review"
        with self.assertRaises(ValueError): p.apply(self.record,attempted,self.state)
        assignment=dict(generation=1,run_id="owner-as-reviewer",reviewer="different-label",profile="c"*64,session="ses_owner",adapter="native-session",obligations=sorted(fixture.e.BASELINE))
        with self.assertRaisesRegex(Exception,"owner proposal session"):
            fixture.e.assign(self.record,assignment)
        self.assertEqual(self.record,before)

    def test_retained_request_corruption_refuses_replay(self):
        request,result=self.admit_proposal()
        admitted=self.record["repair_proposals"][result["admission_id"]]
        admitted["request"]["operation_id"]="changed"
        with self.assertRaises(ValueError): p.apply(self.record,request,self.state)

    def test_owner_artifact_loss_is_checked_after_application(self):
        request,result=self.admit_proposal(); key=result["admission_id"]
        artifacts=self.artifacts(self.record["repair_proposals"][key]["admission"])
        request=dict(schema_version=1,operation_id="collect-owner",expected_revision=self.record["revision"],action="collect",payload=dict(admission_id=key,artifact_sha256={name:c.digest(data) for name,data in artifacts.items()}))
        self.record,collected,_=p.apply(self.record,request,self.state,artifacts); self.record["revision"]+=1
        raw=(self.state/"review-artifacts"/collected["bundle_sha256"]).read_bytes()
        apply_request=dict(schema_version=1,operation_id="apply-owner",expected_revision=self.record["revision"],correction_id=self.correction_id,bundle_sha256=collected["bundle_sha256"])
        fixture.repair.apply_repair(self.record,self.state,apply_request,raw,self.persist)
        path=self.state/"review-artifacts"/c.digest(artifacts["transcript.jsonl"])
        path.chmod(0o600); path.write_bytes(b"lost")
        with self.assertRaises(Exception): fixture.e.validate_collected_retention(self.record,self.state)

if __name__=="__main__": unittest.main()
