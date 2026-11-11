"""Tool schemas: what the model sees."""

FALSIFY_CHECK = {
    "name": "falsify_check",
    "description": (
        "Prove a fix with a negative control before claiming completion. Falsify "
        "re-runs the test command itself, then runs it again on the pre-change tree "
        "with the new tests overlaid. It returns PROVEN only when the command is red "
        "without the change and green with it. Use this after editing code and before "
        "saying a bug is fixed. If it is unproven, write a test that fails without "
        "your change, run it, fix the code, and call this again."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "The test command to prove. Defaults to the last test command run "
                    "in this session (for example 'pytest -q tests/test_pricing.py')."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["fix", "preserve"],
                "description": (
                    "fix (default) requires red-before / green-after. preserve is for "
                    "refactors: the command must be green before and after."
                ),
            },
        },
        "required": [],
    },
}

FALSIFY_STATUS = {
    "name": "falsify_status",
    "description": (
        "Show what Falsify knows about this session: the pre-change baseline, files "
        "changed, test runs seen, and the last verdict. Read-only."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

FALSIFY_CERTIFICATE = {
    "name": "falsify_certificate",
    "description": (
        "Write the proof-of-fix certificate for the last verdict as a self-contained "
        "HTML page, and optionally open it in the browser. The certificate contains "
        "both runs, exit codes, output hashes and a SHA-256 attestation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "open": {
                "type": "boolean",
                "description": "Open the certificate in the default browser.",
            }
        },
        "required": [],
    },
}

FALSIFY_HISTORY = {
    "name": "falsify_history",
    "description": "List recent Falsify certificates and their verdicts.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many certificates to return (default 20, max 100).",
            }
        },
        "required": [],
    },
}

FALSIFY_EXPLAIN = {
    "name": "falsify_explain",
    "description": (
        "Explain the negative-control rule and the exact workflow Falsify expects. "
        "Useful when a check is vetoed and you need to know what would satisfy it."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}
