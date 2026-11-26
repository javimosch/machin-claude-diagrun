#!/usr/bin/env python3
"""End-to-end tests on synthetic transcripts. HOME and --root both point at a
temp directory, so real transcripts are never read."""
import json, os, resource, subprocess, sys, tempfile, datetime

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "diagrun")
NOW = datetime.datetime.now(datetime.timezone.utc)
fails = []

def check(name, got, want):
    ok = abs(got - want) < 1e-6 if isinstance(want, float) else got == want
    if not ok:
        fails.append(f"{name}: got {got!r}, want {want!r}")

def ts(days_ago=0):
    return (NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

n = [0]
def line(kind, sid, content, days=0, usage=None, model=None, mid=None, **extra):
    n[0] += 1
    msg = {"role": kind, "content": content}
    if usage is not None:
        msg.update(id=mid or f"m{n[0]}", model=model, usage=usage)
    d = {"parentUuid": None, "type": kind, "uuid": f"u{n[0]}", "timestamp": ts(days), "sessionId": sid, "message": msg, **extra}
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False)

def U(i=0, o=0, w5=0, w1=0, cr=0):
    return {"input_tokens": i, "output_tokens": o, "cache_creation_input_tokens": w5 + w1,
            "cache_read_input_tokens": cr, "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}

def tool(i, name, **inp):
    return {"type": "tool_use", "id": i, "name": name, "input": inp}

def write(root, rel, lines):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("\n".join(lines) + "\n")

def run(home, *args, env=None):
    e = {"PATH": os.environ["PATH"], "HOME": home, **(env or {})}
    return subprocess.run([BIN, *args], capture_output=True, text=True, env=e, timeout=120)

with tempfile.TemporaryDirectory() as home:
    root = os.path.join(home, "proj")
    # s1: one trivial question on Opus 5.5, streamed as two lines of one message
    q = line("user", "s1", "what is a mutex? SECRETPROMPT <system-reminder>noise</system-reminder>")
    a1 = line("assistant", "s1", [{"type": "text", "text": "a"}], model="claude-opus-5-5", mid="A", usage=U(i=1000, o=10, w1=2000, cr=10000))
    a2 = line("assistant", "s1", [{"type": "text", "text": "b <\"é\">"}], model="claude-opus-5-5", mid="A", usage=U(i=1000, o=500, w1=2000, cr=10000))
    old = line("assistant", "s1", [], days=40, model="claude-opus-5-5", usage=U(i=10**7))
    write(root, "p/s1.jsonl", [old, q, a1, a2, "not json", '{"type":"summary"}'])
    # a resumed copy repeats the same lines: must not be billed twice
    write(root, "p/s1-resumed.jsonl", [q, a1, a2])
    # s2: complex turn with waste, long context, plus a subagent file
    reads = [tool(f"r{k}", "Read", file_path="/x/SECRETFILE.py") for k in range(3)]
    cmds = [tool(f"b{k}", "Bash", command="curl -H SECRETCMD example") for k in range(3)]
    # edited between reads: legitimate, not waste
    legit = [tool("e0", "Read", file_path="/x/ok.py"), tool("e1", "Edit", file_path="/x/ok.py"),
             tool("e2", "Read", file_path="/x/ok.py"), tool("e3", "Edit", file_path="/x/ok.py"), tool("e4", "Read", file_path="/x/ok.py")]
    write(root, "p/s2.jsonl", [
        line("user", "s2", [{"type": "text", "text": "please refactor the whole thing"}]),
        line("assistant", "s2", reads + cmds + legit, model="claude-opus-5-5", usage=U(cr=250000)),
        line("user", "s2", [{"type": "tool_result", "tool_use_id": "b0", "content": "x" * 25000}]),
        line("assistant", "s2", [], model="mystery-model-9", usage=U(i=5000)),
    ])
    write(root, "p/s2/subagents/agent-1.jsonl", [
        line("user", "s2", "sub prompt must not count as a turn", isSidechain=True),
        line("assistant", "s2", [], model="claude-haiku-5-5", usage=U(i=50000, o=1000), isSidechain=True),
    ])

    p = run(home, "scan", "--root", root)
    check("scan exit", p.returncode, 0)
    if p.returncode:
        print(p.stdout, p.stderr); sys.exit(1)
    r = json.loads(p.stdout)
    s1 = (1000*4 + 500*20 + 2000*4*2 + 10000*0.20) / 1e6
    s2 = 250000*0.20 / 1e6
    sub = (50000*0.10 + 1000*0.50) / 1e6
    t = r["totals"]
    check("usd", t["usd"], s1 + s2 + sub)
    check("subagent usd", t["subagent_usd"], sub)
    check("turns", t["turns"], 2)
    check("sessions", t["sessions"], 2)
    check("messages", t["messages"], 3)
    check("unpriced", r["unpriced"], [{"name": "mystery-model-9", "n": 1}])
    check("parts add up", sum(r["parts"].values()), t["usd"])
    haiku = (1000*0.10 + 500*0.50 + 2000*0.10*2 + 10000*0.01) / 1e6
    check("ceiling", r["model_fit"]["per_turn_ceiling_usd"], s1 - haiku)
    check("whole session", r["model_fit"]["whole_session_usd"], s1 - haiku)
    check("whole sessions", r["model_fit"]["whole_sessions"], 1)
    check("kind", r["model_fit"]["by_kind"][0]["kind"], "short_question")
    check("over 150k", r["context"]["over_150k_usd"], 100000*0.20/1e6)
    check("over 100k", r["context"]["over_100k_usd"], 150000*0.20/1e6)
    check("rereads", r["waste"]["unchanged_rereads"], 1)
    check("repeats", r["waste"]["repeated_commands"], 1)
    check("big", r["waste"]["big_results"], [{"name": "Bash", "n": 1}])
    check("no secrets by default", "SECRET" in p.stdout, False)

    p = run(home, "scan", "--root", root, "--examples")
    r = json.loads(p.stdout)
    check("example prompt", r["detail"]["examples"][0]["prompt"], "what is a mutex? SECRETPROMPT")
    check("example file", r["detail"]["rereads"], [{"name": "SECRETFILE.py", "n": 3}])

    out = os.path.join(home, "r.html")
    p = run(home, "report", "--root", root, "--out", out)
    check("report exit", p.returncode, 0)
    html = open(out).read()
    check("html has no secrets", "SECRET" in html, False)
    check("html no script", "<script" in html, False)
    check("html is private", os.stat(out).st_mode & 0o777, 0o600)

    # publishing, against a fake hart that records its arguments
    fake = os.path.join(home, "fakebin"); os.makedirs(fake)
    with open(os.path.join(fake, "hart"), "w") as f:
        f.write('#!/bin/sh\necho "$HART_URL $*" > "$HOME/hart.args"\necho \'{"ok":true,"url":"https://h/a/me/diagrun","version":1}\'\n')
    os.chmod(os.path.join(fake, "hart"), 0o755)
    penv = {"PATH": fake + ":" + os.environ["PATH"]}
    base = ("report", "--root", root, "--out", out, "--publish", "--owner", "me")
    p = run(home, *base, env=penv)
    check("publish url", json.loads(p.stdout or "{}").get("url"), "https://h/a/me/diagrun")
    check("publish unlisted", "--visibility unlisted" in open(os.path.join(home, "hart.args")).read(), True)
    os.remove(os.path.join(home, "hart.args"))
    check("examples need private", run(home, *base, "--examples", env=penv).returncode, 85)
    check("private needs key", run(home, *base, "--private", env=penv).returncode, 85)
    check("owner injection refused", run(home, "report", "--root", root, "--publish", "--owner", "me;id", env=penv).returncode, 85)
    check("refusals never call hart", os.path.exists(os.path.join(home, "hart.args")), False)
    p = run(home, *base, "--private", "--examples", env={**penv, "HART_READ_KEY": "k3y"})
    args = open(os.path.join(home, "hart.args")).read()
    check("private publish", ("--visibility private" in args, "k3y" in args), (True, False))

    # escapes must decode exactly (newline, quote, backslash, accents, surrogate pair)
    esc_root = os.path.join(home, "esc")
    text = 'what is "é" \\ 😀\nnow'
    raw = line("user", "e1", text)
    raw = json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=True)
    write(esc_root, "e.jsonl", [raw, line("assistant", "e1", [], model="claude-opus-5-5", usage=U(i=100, o=10))])
    r = json.loads(run(home, "scan", "--root", esc_root, "--examples").stdout)
    check("escapes", r["detail"]["examples"][0]["prompt"], 'what is "é" \\ 😀 now')

    # memory regression: 18 MB of large escaped tool results under a 300 MB
    # address-space limit (the first loader passed 1 GB on 3 MB)
    big_root = os.path.join(home, "big")
    rows = [line("user", "g", "go"), line("assistant", "g", [], model="claude-opus-5-5", usage=U(i=1))]
    rows += [line("user", "g", [{"type": "tool_result", "tool_use_id": f"z{k}", "content": "line of output\n" * 2000}]) for k in range(600)]
    write(big_root, "g.jsonl", rows)
    cap = lambda: resource.setrlimit(resource.RLIMIT_AS, (300 << 20, 300 << 20))
    p = subprocess.run([BIN, "scan", "--root", big_root], capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": home}, preexec_fn=cap, timeout=60)
    check("memory bounded", p.returncode, 0)

    # cache-write causes: one window walking through every case
    croot = os.path.join(home, "cache")
    def at(sec, w1=0, cr=0, model="claude-opus-5-5", w5=0):
        d = json.loads(line("assistant", "c", [], model=model, usage=U(w1=w1, w5=w5, cr=cr)))
        d["timestamp"] = (NOW - datetime.timedelta(hours=6) + datetime.timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return json.dumps(d, separators=(",", ":"))
    write(croot, "c.jsonl", [
        at(0, w1=20000),                                   # first 20000
        at(10, w1=5000, cr=20000),                         # growth 5000
        at(2000, w1=1000, cr=25000),                       # within 1h: growth 1000
        at(9000, w1=27000),                                # idle: rebuild 26000, growth 1000
        at(9010, w1=28000, model="claude-sonnet-5-5"),     # switch: rebuild 27000, growth 1000
        at(9020, w1=29000, model="claude-sonnet-5-5"),     # unexplained: 28000 + 1000
        at(9030, w1=8000, model="claude-sonnet-5-5"),      # shrunk: 8000
        at(9040, w5=1000, cr=8000, model="claude-sonnet-5-5"),   # growth, now a 5 min cache
        at(9440, w5=10000, model="claude-sonnet-5-5"),     # 400s > 5 min: idle 9000 + 1000
    ])
    r = json.loads(run(home, "scan", "--root", croot).stdout)
    got = {x["cause"]: x["tokens"] for x in r["cache_writes"]["rows"]}
    check("cache causes", got, {"first_request": 20000, "growth": 5000+1000+1000+1000+1000+1000+1000,
          "rebuild_idle_expired": 26000+9000, "rebuild_model_switch": 27000,
          "rebuild_context_shrunk": 8000, "rebuild_unexplained": 28000})
    check("cache usd adds up", sum(x["usd"] for x in r["cache_writes"]["rows"]), r["parts"]["cache_write"])
    check("windows", r["cache_writes"]["windows"], 1)

    # chunked reading: lines straddling the 4 MB boundary, one line longer than
    # two chunks, multi-byte text, and no newline at end of file
    kroot = os.path.join(home, "chunk")
    rows = [line("assistant", "k", [{"type": "text", "text": "é€" * (1 + k % 700)}], model="claude-opus-5-5", usage=U(i=1)) for k in range(9000)]
    rows.insert(4000, line("assistant", "k", [{"type": "text", "text": "z" * (9 << 20)}], model="claude-opus-5-5", usage=U(i=1)))
    os.makedirs(kroot)
    with open(os.path.join(kroot, "k.jsonl"), "w") as f:
        f.write("\n".join(rows))
    r = json.loads(run(home, "scan", "--root", kroot).stdout)
    check("chunked: every line once", (r["totals"]["messages"], r["totals"]["input_tokens"]), (9001, 9001))

    # past 100K, Haiku 5.5's higher tier must apply to every part of the cost
    hroot = os.path.join(home, "tier")
    write(hroot, "h.jsonl", [line("assistant", "h", [], model="claude-haiku-5-5", usage=U(i=1000, o=1000, w1=20000, cr=100000))])
    r = json.loads(run(home, "scan", "--root", hroot).stdout)
    check("tier total", r["totals"]["usd"], (1000*0.5 + 1000*2.5 + 20000*0.5*2 + 100000*0.05) / 1e6)
    check("tier parts add up", sum(r["parts"].values()), r["totals"]["usd"])
    check("tier cache rows", sum(x["usd"] for x in r["cache_writes"]["rows"]), 20000*0.5*2/1e6)

    # idle rebuilds: one pause per trigger, each in its own pause bucket
    iroot = os.path.join(home, "idle")
    clock = [0]
    def stamp(raw, advance):
        clock[0] += advance
        d = json.loads(raw)
        d["timestamp"] = (NOW - datetime.timedelta(days=5) + datetime.timedelta(seconds=clock[0])).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return json.dumps(d, separators=(",", ":"))
    def req(advance, calls=(), cr=0):
        return stamp(line("assistant", "i", list(calls), model="claude-opus-5-5", usage=U(w1=10000, cr=cr)), advance)
    def usr(content, advance=0, **kw):
        return stamp(line("user", "i", content, **kw), advance)
    def result(i):
        return [{"type": "tool_result", "tool_use_id": i, "content": "ok"}]
    write(iroot, "i.jsonl", [
        usr("start"), req(1),
        # typed after 90 min; a later injected line must not hide it
        usr("back again", 5400), usr("injected", isMeta=True), req(1),
        usr("<task-notification>done</task-notification>", 4000), req(1, [tool("q1", "AskUserQuestion")]),
        usr(result("q1"), 10000), req(1, [tool("sh", "Bash", command="sleep 9999 && true")]),
        usr(result("sh"), 40000), req(1, [tool("w1", "ScheduleWakeup")]),
        usr(result("w1"), 1), req(1, cr=10000),
        usr("/loop check the build", 90000), req(1, cr=3000),
    ])
    r = json.loads(run(home, "scan", "--root", iroot, "--days", "30").stdout)
    idle = r["cache_writes"]["idle"]
    check("idle pairs", sorted((x["pause"], x["trigger"]) for x in idle["rows"]), sorted([
        ("1h-2h", "typed_prompt"), ("1h-2h", "background_task"), ("2h-8h", "question_answered"),
        ("8h-24h", "tool_result_or_approval"), ("over_24h", "after_scheduled_wakeup")]))
    check("idle pause order", [g["name"] for g in idle["by_pause"]], ["1h-2h", "2h-8h", "8h-24h", "over_24h"])
    total = [x["usd"] for x in r["cache_writes"]["rows"] if x["cause"] == "rebuild_idle_expired"][0]
    for key in ("rows", "by_pause", "by_trigger"):
        check(f"idle {key} add up", sum(x["usd"] for x in idle[key]), total)

    check("no data exit", run(home, "scan", "--root", os.path.join(home, "none")).returncode, 92)
    check("bad days", run(home, "scan", "--days", "x").returncode, 85)
    p = run(home, "bogus")
    check("typed error", json.loads(p.stderr)["error"]["type"], "invalid_argument")
    # cli-output-spec / cli-guide-spec behaviour the validator does not cover
    cat = json.loads(run(home, "help-json").stdout)
    check("catalog", (sorted(cat["commands"]), cat["env"]), (["guide", "help-json", "report", "scan", "version"], ["HOME", "HART_URL", "HART_READ_KEY"]))
    g = json.loads(run(home, "guide").stdout)
    check("guide keys", [k for k in ("diagrun", "one_liner", "model", "loop", "concepts", "commands", "examples", "gotchas") if k not in g], [])
    check("guide version", g["version"], cat["version"])
    human = run(home, "guide", "--human").stdout
    check("human has every gotcha", all(x in human for x in g["gotchas"]), True)
    check("version json", json.loads(run(home, "version", "--json").stdout)["version"], g["version"])
    check("non-interactive flags", run(home, "scan", "--root", root, "--yes", "--no-interactive", "--json", "-y").returncode, 0)
    err = json.loads(run(home, "scan", "--root", os.path.join(home, "none")).stderr)
    check("error shape", (err["ok"], err["error"]["recoverable"], len(err["error"]["suggestions"]) > 0), (False, False, True))
    with open(os.path.join(fake, "hart"), "w") as h:
        h.write("#!/bin/sh\necho boom >&2\nexit 1\n")
    p = run(home, *base, env=penv)
    err = json.loads(p.stderr)["error"]
    check("publish failure is retryable", (p.returncode, err["code"], err["recoverable"]), (105, 105, True))
    p = run(home, "report", "--root", root, "--out", os.path.join(home, "no", "dir", "r.html"))
    check("unwritable report", (p.returncode, json.loads(p.stderr.strip().splitlines()[-1])["error"]["type"]), (92, "write_failed"))

print("\n".join(fails) if fails else "all checks passed")
sys.exit(1 if fails else 0)
