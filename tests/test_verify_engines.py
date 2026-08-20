from scripts.verify_engines import build_parser


def test_verify_engines_parser_accepts_ephemeral_proxy():
    args = build_parser().parse_args(
        ["--proxy", "socks5://proxy.example:1080", "--skip-download"]
    )

    assert args.proxy == "socks5://proxy.example:1080"
    assert args.skip_download is True
