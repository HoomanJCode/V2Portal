from scripts.verify_acceptance import Checks, build_parser, run_smoke


def test_credential_free_acceptance_smoke():
    checks = Checks()

    assert run_smoke(checks) is True
    assert checks.results
    assert all(ok for _, ok, _ in checks.results)


def test_acceptance_parser_supports_json_output():
    args = build_parser().parse_args(["--json"])

    assert args.json is True


def test_checks_serialize_machine_readable_results():
    checks = Checks(quiet=True)
    checks.check("synthetic", True, "ok")

    assert checks.as_dict() == {
        "ok": True,
        "checks": [{"name": "synthetic", "ok": True, "detail": "ok"}],
    }
