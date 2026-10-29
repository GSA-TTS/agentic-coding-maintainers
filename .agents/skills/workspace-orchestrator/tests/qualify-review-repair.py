#!/usr/bin/env python3
"""Explicit live qualification fixture driver, run only in a disposable guest.

The operator transfers emitted source/context to a separate model guest and
returns its actual bundle for each phase. No fabricated response fallback.
This driver never provisions networking or invokes a model on its own.
"""

import argparse
import base64
import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"
OBLIGATIONS = ["correctness", "acceptance", "test-adequacy", "maintainability", "baseline-security"]


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def retain_request(path, request):
    if path.exists():
        prior = json.loads(path.read_bytes())
        if {key:value for key,value in prior.items() if key != "expected_revision"} != {key:value for key,value in request.items() if key != "expected_revision"}:
            raise ValueError("phase retry changed request content")
        return prior
    path.write_bytes(canonical(request))
    return request


def require_seeded_baseline(baseline):
    if baseline["returncode"] != 0 or baseline["stderr"] or baseline["stdout"] != "[4, -1, 1, 12]\n":
        raise ValueError("baseline execution did not measure the seeded defect")


def require_adjudication(finding_id, assessment):
    if finding_id not in assessment.get("unresolved_findings", []):
        raise ValueError("operator must adjudicate a retained finding against the seeded arithmetic invariant; no nonempty-finding shortcut")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("init", "review", "proposal", "rereview"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--binary-sha256", required=True)
    parser.add_argument("--owner-pid", type=int, required=True)
    parser.add_argument("--model", default="usai/gpt-6-astra")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--isolated-guest", action="store_true")
    parser.add_argument("--finding-id", help="operator-adjudicated initial finding matching the seeded invariant")
    args = parser.parse_args()
    if not args.isolated_guest:
        raise ValueError("operator must provide an isolated qualification guest")
    root = args.root.resolve()
    root.mkdir(mode=0o700, exist_ok=True)
    source = root / "work" / "candidate"
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700, exist_ok=True)
    env = {**os.environ, "WORKSPACE_ORCHESTRATOR_ROOT": str(root)}
    phase_receipt = evidence / ("phase-" + args.phase + ".json")
    phase_input = {"phase":args.phase, "finding_id":args.finding_id,
                   "bundle":{name:sha((args.bundle/name).read_bytes()) for name in ("receipt.json","transcript.jsonl","session-export.json","stderr.txt","export-stderr.txt")} if args.bundle else None}
    if phase_receipt.exists():
        prior = json.loads(phase_receipt.read_bytes())
        if prior["input"] != phase_input:
            raise ValueError("completed phase replay changed inputs")
        print(json.dumps(prior["result"], sort_keys=True))
        return
    session_file = evidence / "sessions.json"
    if not session_file.exists():
        session_file.write_bytes(canonical({role:"ses_qualification_"+uuid.uuid4().hex for role in ("before","owner","after")}))
    sessions = json.loads(session_file.read_bytes())

    def tool(name, *arguments, accepted=(0,)):
        result = subprocess.run(["python3", "-I", "-B", str(BIN / name), *map(str, arguments)],
                                env=env, capture_output=True, text=True, timeout=60)
        if result.returncode not in accepted:
            raise ValueError(f"{name} failed ({result.returncode}): {result.stdout} {result.stderr}")
        return json.loads(result.stdout)

    def state():
        return tool("orchestrator-state.py", "show", "qualification")

    def change(name, action, payload, operation):
        request = dict(schema_version=1, operation_id=operation, expected_revision=state()["revision"], action=action, payload=payload)
        path = evidence / f"{operation}.json"
        retain_request(path, request)
        return tool(name, "qualification", "--request", path)

    def git(*arguments):
        result = subprocess.run(["git", "-C", str(source), "-c", "user.name=Qualification", "-c", "user.email=qualification@example.invalid",
                                 "-c", "commit.gpgsign=false", *arguments], capture_output=True, text=True, timeout=20, check=True)
        return result.stdout.strip()

    def oracle(label):
        # Independently fixed oracle, never replaced by model-produced test text.
        result = subprocess.run(["python3", "-I", "-B", "-c",
            "import runpy,sys; f=runpy.run_path(sys.argv[1])['double']; print([f(x) for x in (3,-2,0,11)])", str(source / "calc.py")],
            capture_output=True, text=True, timeout=10)
        record = dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                      expected="[6, -4, 0, 22]\n", passed=result.returncode == 0 and result.stdout == "[6, -4, 0, 22]\n" and not result.stderr)
        (evidence / f"oracle-{label}.json").write_bytes(canonical(record))
        return record

    def stage_review(label):
        record = state()
        captured = tool("review-packet.py", "--repo", source, "--repository", "fixture/qualification", "--base", record["base_sha"],
                        "--head", record["head_sha"], "--comparison", "direct", "--store", root / "packets")
        packet_path = root / "packets" / (captured["packet"] + ".json")
        packet = json.loads(packet_path.read_bytes())
        change("review-evidence.py", "begin", dict(packet=captured["packet"], policy=packet["policy_sha256"], base=record["base_sha"], head=record["head_sha"], obligations=OBLIGATIONS), "begin-"+label)
        record = state()
        generation = record["review_protocol"]["generations"][-1]
        context = dict(acceptance=record["acceptance_criteria"], prior_findings=[finding for gen in record["review_protocol"]["generations"] for report in gen["reports"].values() for finding in report["findings"]],
                       oracle=json.loads((evidence / f"oracle-{label}.json").read_bytes()))
        session = sessions[label]
        profile = sha(args.profile.read_bytes())
        change("review-evidence.py", "assign", dict(generation=generation["number"], run_id=label, reviewer="independent-reviewer", profile=profile,
            obligations=OBLIGATIONS, adapter="native-session", session=session), "assign-"+label)
        request = dict(schema_version=1, operation_id="admit-"+label, expected_revision=state()["revision"], action="admit", payload=dict(
            generation=generation["number"], run_id=label, binary_sha256=args.binary_sha256, model=args.model, agent="bounded-worker", cwd="/home/node/review",
            sources={"/candidate/"+name:dict(path_base64=base64.b64encode(name.encode()).decode(),side="after") for name in ("calc.py","test_calc.py")}, context=context))
        path=evidence / f"admit-{label}.json"
        path.write_bytes(canonical(request))
        result=tool("review-collect.py","qualification","--request",path,"--packet",packet_path)
        (evidence / f"admission-{label}.json").write_bytes(canonical(result))
        (evidence / f"context-{label}.json").write_bytes(canonical(context))
        return dict(phase=label,session=session,role="review",context_path=str(evidence/f"context-{label}.json"),source_path=str(source),obligations=OBLIGATIONS)

    def ingest_review(label):
        if args.bundle is None:
            raise ValueError("real runtime bundle required")
        files=("receipt.json","transcript.jsonl","session-export.json","stderr.txt","export-stderr.txt")
        admitted=json.loads((evidence/f"admission-{label}.json").read_bytes())["admission_id"]
        request=dict(schema_version=1,operation_id="collect-"+label,expected_revision=state()["revision"],action="collect",
                     payload=dict(admission_id=admitted,artifact_sha256={name:sha((args.bundle/name).read_bytes()) for name in files}))
        path=evidence/f"collect-{label}.json"
        retain_request(path, request)
        tool("review-collect.py","qualification","--request",path,"--bundle",args.bundle)
        change("review-accept.py","accept-collected",dict(admission_id=admitted),"accept-"+label)

    if args.phase == "init":
        source.mkdir(parents=True, exist_ok=False)
        git("init","-q","-b","qualification")
        (source/"README").write_text("Ordinary-code qualification fixture\n")
        git("add","."); git("commit","-qm","baseline"); base=git("rev-parse","HEAD")
        (source/"calc.py").write_text("def double(x):\n    return x + 1\n")
        (source/"test_calc.py").write_text("from calc import double\nassert double(3) == 6\nassert double(-2) == -4\nassert double(0) == 0\n")
        for name in ("calc.py","test_calc.py"): (source/name).chmod(0o644)
        git("add","."); git("commit","-qm","candidate"); head=git("rev-parse","HEAD")
        tool("orchestrator-state.py","create","qualification","--scope","qualification:ordinary-code","--kind","implementation","--repo","fixture/qualification",
             "--branch","qualification","--worktree",source,"--base-sha",base,"--head-sha",head,"--owned-path","calc.py","--owned-path","test_calc.py",
             "--acceptance","double(x) must equal 2*x for integers, including negative and zero inputs")
        tool("orchestrator-state.py","claim","qualification","--owner","implementation-owner","--pid",args.owner_pid)
        tool("orchestrator-state.py","transition","qualification","Implementing")
        tool("orchestrator-state.py","transition","qualification","Reviewing")
        baseline = oracle("before")
        require_seeded_baseline(baseline)
        result=stage_review("before")
    elif args.phase == "review":
        ingest_review("before")
        assessment=tool("review-evidence.py","qualification",accepted=(3,))
        require_adjudication(args.finding_id, assessment)
        (evidence/"finding-adjudication.json").write_bytes(canonical({"finding_id":args.finding_id,"decision":"operator supplied semantic match to double(x)==2*x", "source":"explicit --finding-id, not automatic classification"}))
        if state()["state"] == "Reviewing":
            tool("orchestrator-state.py","transition","qualification","Rework")
        prepared_path = evidence/"prepared-correction.json"
        if not prepared_path.exists():
            correction=tool("repair-apply.py","qualification","prepare","--expected-revision",state()["revision"])
            prepared_path.write_bytes(canonical(correction))
        else:
            correction=json.loads(prepared_path.read_bytes())
        if state()["state"] == "Rework":
            tool("orchestrator-state.py","claim","qualification","--owner","implementation-owner","--pid",args.owner_pid)
        if state()["state"] == "Claimed":
            tool("orchestrator-state.py","transition","qualification","Implementing")
        admission=change("repair-proposal.py","admit",dict(correction_id=correction["correction_id"],session=sessions["owner"],model=args.model,agent="bounded-worker",
            binary_sha256=args.binary_sha256,profile_sha256=sha(args.profile.read_bytes()),cwd="/home/node/review",sources={"/candidate/"+name:name for name in ("calc.py","test_calc.py")}),"owner-admission")
        (evidence/"owner-admission.json").write_bytes(canonical(admission)); (evidence/"context-owner.json").write_bytes(canonical(admission["context"]))
        result=dict(phase="owner",session=sessions["owner"],role="owner-proposal",context_path=str(evidence/"context-owner.json"),source_path=str(source))
    elif args.phase == "proposal":
        if args.bundle is None: raise ValueError("actual owner bundle required")
        admission=json.loads((evidence/"owner-admission.json").read_bytes())
        files=("receipt.json","transcript.jsonl","session-export.json","stderr.txt","export-stderr.txt")
        request=dict(schema_version=1,operation_id="owner-collection",expected_revision=state()["revision"],action="collect",payload=dict(admission_id=admission["admission_id"],artifact_sha256={name:sha((args.bundle/name).read_bytes()) for name in files}))
        path=evidence/"owner-collection.json"
        if path.exists():
            retained=json.loads(path.read_bytes())
            if any(retained[key] != request[key] for key in ("schema_version","operation_id","action","payload")):
                raise ValueError("owner collection retry changed its payload")
            request=retained
        else:
            path.write_bytes(canonical(request))
        collected=tool("repair-proposal.py","qualification","--request",path,"--bundle",args.bundle)
        if collected["status"] != "PROPOSAL_COLLECTED": raise ValueError("owner unable to propose; stop without fabricated repair")
        request=dict(schema_version=1,operation_id="apply-owner",expected_revision=state()["revision"],correction_id=admission["context"]["correction_id"],bundle_sha256=collected["bundle_sha256"])
        path=evidence/"apply-owner.json"
        if path.exists():
            retained=json.loads(path.read_bytes())
            if any(retained[key] != request[key] for key in ("schema_version","operation_id","correction_id","bundle_sha256")):
                raise ValueError("owner application retry changed its payload")
            request=retained
        else:
            path.write_bytes(canonical(request))
        bundle_path=root/".orchestrator"/"review-artifacts"/collected["bundle_sha256"]
        applied=tool("repair-apply.py","qualification","apply","--request",path,"--bundle",bundle_path)
        snapshot=canonical(state())
        if tool("repair-apply.py","qualification","apply","--request",path,"--bundle",bundle_path) != applied or canonical(state()) != snapshot: raise ValueError("repair replay mutated state")
        if not oracle("after")["passed"]: raise ValueError("model repair failed independent oracle")
        git("add","calc.py","test_calc.py"); git("commit","-qm","model-proposed owner repair")
        tool("orchestrator-state.py","update-head","qualification",git("rev-parse","HEAD"))
        result=stage_review("after")
    else:
        ingest_review("after")
        assessment=tool("review-evidence.py","qualification",accepted=(3,))
        if assessment.get("unresolved_findings") or assessment.get("missing_obligations") or assessment.get("review_process") != "CLAIMS_COMPLETE":
            raise ValueError("fresh review did not complete coverage/dispositions")
        record=state()
        result=dict(status="LIVE_LOOP_OBSERVED",review=assessment,head=record["head_sha"],original_findings=[finding for generation in record["review_protocol"]["generations"] for report in generation["reports"].values() for finding in report["findings"]],
                    candidate_ready=False,qualification="real reviewer/owner/rereviewer; independently fixed behavioral oracle; controlled isolated fixture, not production PR automation")
        (evidence/"outcome.json").write_bytes(canonical(result))
    phase_receipt.write_bytes(canonical({"input":phase_input,"result":result}))
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__": main()
