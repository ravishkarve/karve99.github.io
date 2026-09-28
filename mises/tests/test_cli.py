from pymises.cli import main


def test_cli_example_run_and_blade(tmp_path, capsys):
    assert main(["example", "compressor", str(tmp_path)]) == 0
    cfg = tmp_path / "compressor.toml"
    assert cfg.exists()
    assert main(["run", str(cfg), "-o", str(tmp_path / "out"), "--no-plots", "-q"]) == 0
    assert (tmp_path / "out" / "result.json").exists()
    assert (tmp_path / "out" / "result_surface.csv").exists()
    assert main(["blade", str(cfg), "-w", str(tmp_path / "blade.out")]) == 0
    assert (tmp_path / "blade.out").read_text().splitlines()[0].startswith("C4")


def test_cli_verify_quick(tmp_path):
    assert main(["verify", "--quick", "-q", "-o", str(tmp_path)]) == 0
    assert (tmp_path / "verification.md").exists()
