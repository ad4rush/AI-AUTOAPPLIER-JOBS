import subprocess
import shutil
from pathlib import Path
from typing import Tuple, Optional

def compile_latex_to_pdf(tex_path: Path, output_dir: Optional[Path] = None) -> Tuple[bool, str, Optional[Path]]:
    """
    Compiles a .tex file to .pdf using the local tectonic engine.
    Returns (success, log_output, pdf_path).
    """
    tex_path = Path(tex_path).resolve()
    if not tex_path.exists():
        return False, f"TeX file not found: {tex_path}", None

    out_dir = Path(output_dir).resolve() if output_dir else tex_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    tectonic_bin = shutil.which("tectonic")
    if not tectonic_bin:
        # Check standard homebrew path
        if Path("/opt/homebrew/bin/tectonic").exists():
            tectonic_bin = "/opt/homebrew/bin/tectonic"
        else:
            return False, "tectonic compiler not found in PATH or /opt/homebrew/bin", None

    cmd = [
        tectonic_bin,
        "--outdir", str(out_dir),
        str(tex_path)
    ]

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            cwd=str(tex_path.parent)
        )
        output = proc.stdout + "\n" + proc.stderr
        expected_pdf = out_dir / (tex_path.stem + ".pdf")

        if proc.returncode == 0 and expected_pdf.exists():
            return True, output, expected_pdf
        else:
            return False, f"Compilation failed (code {proc.returncode}):\n{output}", None
    except subprocess.TimeoutExpired:
        return False, "Tectonic compilation timed out (120s)", None
    except Exception as e:
        return False, f"Unexpected compilation error: {str(e)}", None
