# GitHub CLI TLS On Managed macOS

Use this guide when `gh` can reach GitHub's API but fails TLS verification while
downloading GitHub Actions logs on a managed macOS host.

## Cause

Go 1.27 on macOS honors `SSL_CERT_FILE` and `SSL_CERT_DIR`. If either variable is
set, a Go program such as `gh` can use the configured on-disk CA bundle instead
of the macOS platform verifier. An explicit bundle that omits an organization CA
can therefore break TLS to intercepted services even when that CA is installed
and trusted by macOS.

This can appear service-specific. `gh api` connects to `api.github.com`, which
may not be intercepted, while Actions log downloads redirect to separate storage
that may be intercepted. A successful API request does not prove that log
storage is reachable with the same trust configuration.

## Preferred Fix

Unset **both** variables for each `gh` invocation so Go uses the macOS platform
verifier and its installed trust:

```bash
env -u SSL_CERT_FILE -u SSL_CERT_DIR gh api rate_limit
env -u SSL_CERT_FILE -u SSL_CERT_DIR gh run view <id> --log-failed
```

Both commands must exit successfully. The second command may produce no output
when the selected run has no failed-step logs; successful empty output is valid.
Use a run known to contain failed steps when verifying log contents.

For the affected maintainer host, verification returned `rc=0` both with the
inherited complete bundle and with both variables unset. This confirms that the
GitHub API and redirected Actions log-storage paths are trusted in either safe
configuration; it does not make an incomplete explicit bundle safe.

Setting only one variable to an empty value is not sufficient if the other
remains exported. Remove both from the command environment (or from the shell
configuration that exports them) and retry.

## Explicit Bundle

If another tool requires a CA file, use a complete, locally generated bundle
that includes the organization CA already installed by host administrators.
Keep `SSL_CERT_DIR` unset so it cannot select a different on-disk trust source:

```bash
env -u SSL_CERT_DIR SSL_CERT_FILE=/absolute/path/to/complete-ca-bundle.pem \
  gh api rate_limit
env -u SSL_CERT_DIR SSL_CERT_FILE=/absolute/path/to/complete-ca-bundle.pem \
  gh run view <id> --log-failed
```

CA bundles are host-derived security material. Never commit a host CA bundle,
certificate export, or generated trust store to this repository.

## Diagnosis Only

For Go 1.27, this command can confirm that the explicit-bundle override is the
cause by restoring the platform-verifier behavior for one process:

```bash
GODEBUG=x509sslcertoverrideplatform=0 gh run view <id> --log-failed
```

Treat `GODEBUG=x509sslcertoverrideplatform=0` as a temporary diagnostic, not a
durable fix. Prefer unsetting both certificate variables. Do not disable TLS
verification or use insecure flags as a workaround.
