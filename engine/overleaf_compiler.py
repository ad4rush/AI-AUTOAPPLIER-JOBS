#!/usr/bin/env python3
"""
Autonomous Overleaf Compiler & PDF Exporter (100% Programmatic).
Automates Overleaf web editor compilation via ego-browser on Profile 2 (College Profile).

Features:
- Connects to existing Overleaf session or launches project 'resume2.0'.
- Dispatches raw LaTeX code into CodeMirror 6 editor.
- Triggers Recompile with pdfLaTeX (TeX Live 2025).
- Automatically fetches and saves the output PDF to the specified output destination.
"""

import sys
import os
import json
import time
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

OVERLEAF_PROJECT_ID = os.getenv("OVERLEAF_PROJECT_ID", "69f634ddee1c464cc9dc7c7c")
OVERLEAF_TASK_SPACE = "check_overleaf_Profile2"


def compile_latex_on_overleaf(
    tex_path: str,
    output_pdf_path: Optional[str] = None,
    timeout_seconds: int = 40
) -> Dict[str, Any]:
    """
    Compiles a .tex file on Overleaf programmatically and writes the resulting PDF.
    """
    tex_file = Path(tex_path).resolve()
    if not tex_file.exists():
        return {"status": "ERROR", "message": f"Source .tex not found: {tex_path}"}

    if output_pdf_path is None:
        output_pdf_path = str(tex_file.with_suffix(".pdf"))
    output_pdf = Path(output_pdf_path).resolve()

    with open(tex_file, "r", encoding="utf-8") as f:
        tex_content = f.read()

    # Dynamically inject candidate credentials from .env to preserve privacy in repo source
    try:
        from engine.claude_tailor import inject_candidate_profile
        tex_content = inject_candidate_profile(tex_content)
    except Exception:
        pass

    runner_script = f"""(async () => {{
  const fs = await import("node:fs/promises");

  const spaces = await listTaskSpaces();
  let s = spaces.find(x => x.name === "{OVERLEAF_TASK_SPACE}");
  let task;
  if (s) {{
    if (s.ownership === "agent") {{
      task = await taskSpace(s.id);
    }} else {{
      try {{
        task = await takeOverTaskSpace(s.id);
      }} catch (e) {{
        task = await taskSpace("{OVERLEAF_TASK_SPACE}_" + Date.now(), {{ profileId: "Profile 2" }});
      }}
    }}
  }} else {{
    task = await taskSpace("{OVERLEAF_TASK_SPACE}", {{ profileId: "Profile 2" }});
  }}

  const page = task.page("p1");
  const targetUrl = "https://www.overleaf.com/project/{OVERLEAF_PROJECT_ID}";
  const currentUrl = await page.url();

  if (!currentUrl.includes("{OVERLEAF_PROJECT_ID}")) {{
    console.log("[OverleafCompiler] Navigating to " + targetUrl + " ...");
    await page.goto(targetUrl, {{ waitUntil: "domcontentloaded", timeout: 30000 }});
    await new Promise(r => setTimeout(r, 4000));
  }}

  // Ensure CodeMirror 6 editor is ready
  let hasView = false;
  for (let w = 0; w < 10; w++) {{
    hasView = await page.evaluate(() => {{
      const cmContent = document.querySelector(".cm-content");
      return !!(cmContent && cmContent.cmView && cmContent.cmView.view);
    }});
    if (hasView) break;
    await new Promise(r => setTimeout(r, 1000));
  }}

  if (!hasView) {{
    throw new Error("CodeMirror 6 editor view not available in Overleaf session.");
  }}

  console.log("[OverleafCompiler] Injecting LaTeX source (" + {len(tex_content)} + " chars)...");
  await page.evaluate((tex) => {{
    const cmContent = document.querySelector(".cm-content");
    const view = cmContent.cmView.view;
    view.dispatch({{
      changes: {{ from: 0, to: view.state.doc.length, insert: tex }}
    }});
  }}, {json.dumps(tex_content)});

  console.log("[OverleafCompiler] Triggering Recompile...");
  await page.evaluate(() => {{
    const btn = document.querySelector(".compile-button");
    if (btn) btn.click();
  }});

  // Poll for compile to finish
  let compiled = false;
  for (let i = 0; i < 20; i++) {{
    await new Promise(r => setTimeout(r, 2000));
    const status = await page.evaluate(() => {{
      const btn = document.querySelector(".compile-button");
      const loading = btn ? btn.getAttribute("data-ol-loading") : "unknown";
      const pdfLink = document.querySelector("a[href*=\\"/output/output.pdf\\"]");
      const errorBadge = document.querySelector(".logs-tab-badge.badge-danger");
      return {{
        loading,
        hasPdf: !!pdfLink,
        pdfUrl: pdfLink ? pdfLink.href : null,
        error: errorBadge ? errorBadge.innerText : null
      }};
    }});

    if (status.loading === "false" && status.hasPdf && i > 0) {{
      compiled = true;
      break;
    }}
    if (status.error && status.loading === "false") {{
      throw new Error("Compilation failed on Overleaf: " + status.error);
    }}
  }}

  if (!compiled) {{
    throw new Error("Overleaf compilation timed out without producing PDF link.");
  }}

  console.log("[OverleafCompiler] Downloading PDF artifact from Overleaf...");
  const pdfBytesB64 = await page.evaluate(async () => {{
    const pdfLink = document.querySelector("a[href*=\\"/output/output.pdf\\"]");
    const res = await fetch(pdfLink.href);
    const buf = await res.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = "";
    for (let i = 0; i < bytes.byteLength; i++) binary += String.fromCharCode(bytes[i]);
    return window.btoa(binary);
  }});

  const buffer = Buffer.from(pdfBytesB64, "base64");
  await fs.writeFile({json.dumps(str(output_pdf))}, buffer);
  console.log("[OverleafCompiler] Saved compiled PDF to: " + {json.dumps(str(output_pdf))} + " (" + buffer.length + " bytes)");
}})().catch(err => {{
  console.error("[OverleafCompiler Error]", err);
  process.exit(1);
}});"""

    proc = subprocess.run(["ego-browser", "nodejs"], input=runner_script, text=True, capture_output=True)
    if proc.returncode == 0 and output_pdf.exists():
        return {
            "status": "SUCCESS",
            "tex_path": str(tex_file),
            "output_pdf": str(output_pdf),
            "size_bytes": output_pdf.stat().st_size
        }
    else:
        return {
            "status": "ERROR",
            "message": "Overleaf compilation failed",
            "details": proc.stdout + "\n" + proc.stderr
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 engine/overleaf_compiler.py <path_to_tex> [output_pdf_path]")
        sys.exit(1)
    
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    res = compile_latex_on_overleaf(src, out)
    print(json.dumps(res, indent=2))
