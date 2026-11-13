import subprocess
import shutil
import os
from pathlib import Path
from typing import Tuple, Optional

def compile_latex_to_pdf(tex_path: Path, output_dir: Optional[Path] = None, prefer_overleaf: bool = True) -> Tuple[bool, str, Optional[Path]]:
    """
    Compiles a .tex file to .pdf.
    Prioritizes Overleaf programmatic compilation (TeX Live 2025, pdfLaTeX) to ensure
    identical typography and font rendering without local font/mapping hassle.
    Falls back to local tectonic engine if Overleaf session is unavailable.
    Returns (success, log_output, pdf_path).
    """
    tex_path = Path(tex_path).resolve()
    if not tex_path.exists():
        return False, f"TeX file not found: {tex_path}", None

    out_dir = Path(output_dir).resolve() if output_dir else tex_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    expected_pdf = out_dir / (tex_path.stem + ".pdf")

    # 1. Try Overleaf Programmatic Compiler first
    if prefer_overleaf:
        try:
            from engine.overleaf_compiler import compile_latex_on_overleaf
            res = compile_latex_on_overleaf(str(tex_path), str(expected_pdf), timeout_seconds=30)
            if res.get("status") == "SUCCESS" and expected_pdf.exists() and expected_pdf.stat().st_size > 1000:
                return True, f"Successfully compiled on Overleaf (size: {expected_pdf.stat().st_size} bytes)", expected_pdf
        except Exception as e:
            # Fall back to local tectonic
            pass

    # 2. Fallback to local Tectonic compiler
    tectonic_bin = shutil.which("tectonic")
    if not tectonic_bin:
        # Check standard homebrew path
        if Path("/opt/homebrew/bin/tectonic").exists():
            tectonic_bin = "/opt/homebrew/bin/tectonic"
        else:
            return False, "Neither Overleaf nor tectonic compiler available", None

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

        if proc.returncode == 0 and expected_pdf.exists():
            return True, output, expected_pdf
        else:
            return False, f"Compilation failed (code {proc.returncode}):\n{output}", None
    except subprocess.TimeoutExpired:
        return False, "Tectonic compilation timed out (120s)", None
    except Exception as e:
        return False, f"Unexpected compilation error: {str(e)}", None
