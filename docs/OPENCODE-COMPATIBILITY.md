# OpenCode Compatibility

The maintainer skills use the portable Agent Skills layout and support OpenCode
1.19+ and 2.0+.

## Verified Interfaces

- `.agents/skills/<name>/SKILL.md` portable layout and v1 enumeration
- portable `name`, `description`, `compatibility`, and string metadata
- project-local `.opencode/agents/*.md` profiles using `mode`, `steps`, and
  `permission`
- no deprecated `tools` or `maxSteps` profile fields
- ordinary Bash/Python skill executables, independent of the OpenCode process

OpenCode v2 uses plural top-level JSON fields (`agents`, `permissions`,
`plugins`, `commands`, `providers`). The v1 aliases remain accepted but are
deprecated. V2 custom providers also use `package` and `settings`, replacing v1
`npm` and `options`:

```text
v1: provider.usai.npm / provider.usai.options
v2: providers.usai.package / providers.usai.settings
```

The supplied Markdown profiles avoid these top-level JSON differences.

OpenCode v2 `debug config` reports configuration sources rather than the v1
merged object. V2 debug commands can also collide with its managed background
service port. The compatibility probe therefore uses `run --standalone`, an
explicit minimal environment, isolated HOME/config/data/cache/state/temp
directories, and an intentionally invalid model. Every known custom agent must
reach `provider.no-route`; an unknown agent must fail earlier with
`Agent not found`. No intended model request succeeds; the invalid route is not
an enforced network sandbox, so the test makes no no-network claim. Temporary
configuration, logs, stdout, and stderr are removed on success or failure.

OpenCode v1 exposes `debug skill`, and the probe asserts both skill names. V2
2.0.32 has no equivalent debug subcommand. Its model-free probe verifies that
the project skill directory is watched; actual v2 skill loading is covered only
by the separately disclosed manual live-provider probe below.

## Runtime Probe

```bash
OPENCODE_V1=/path/to/opencode-v1 \
OPENCODE_V2=/path/to/opencode-v2 \
bash tests/opencode-compat-test.sh
```

Without both runtime paths, portable frontmatter checks run and the runtime
probe explicitly reports `SKIP`.

## Live Provider Probe

On 2026-10-17 a maintainer manually ran OpenCode 2.0.32 against USAi with a minimal disposable
configuration using `providers`, `package: "@ai-sdk/openai-compatible"`, and
`settings`; the read-only `qa-reviewer` returned `V2_OK` without tool calls. A
second bounded probe loaded both named skills through the native skill tool. The
credential was supplied only through the process environment. The maintainer
searched the disposable config, data, cache, state, stdout, stderr, and log tree
for the exact credential and found no match, then staged the probe tree for
disposal. CI does not reproduce this credentialed test. This verifies the config
shape and one model route, not blanket model or provider compatibility.
