from scripts.verify_acceptance import Checks, run_smoke


def test_credential_free_acceptance_smoke():
    checks = Checks()

    assert run_smoke(checks) is True
    assert checks.results
    assert all(ok for _, ok, _ in checks.results)
