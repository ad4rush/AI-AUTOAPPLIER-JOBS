# Gold-Standard Resume Tailoring & Visual Review Procedure

## 1. Structural Baseline Architecture
All future resume tailoring in this platform strictly inherits from the Overleaf gold-standard:
- Source: `master_resume/overleaf_source/DATA AND ML.tex`
- Output Format: 100% strict 1-page XeTeX compilation via Tectonic.
- Target Page Budget: Must fill **90%–95% of printable A4 page height** from header down to the bottom margin with **ZERO awkward blank whitespace** at the bottom.

### Core Geometry & Spacing
```latex
\usepackage{geometry}
\geometry{a4paper, margin=0.38in, top=0.24in, bottom=0.20in}
\linespread{0.97}
\titlespacing{\section}{0pt}{4.5pt}{2.5pt}
\setlist[itemize]{
    leftmargin=1.2em,
    labelsep=0.4em,
    itemsep=0.4pt,
    parsep=0pt,
    topsep=1.2pt,
    after=\vspace{0.15em}
}
```

## 2. Typography & Font Engine (macOS Native Lato)
In XeTeX / Tectonic, standard `\usepackage[default]{lato}` without fontspec falls back to Computer Modern `SFRM1000` (which has weak bold contrast).
The frozen production standard loads true OpenType/TrueType Lato:
```latex
\usepackage{fontspec}
\setmainfont{Lato}[
  Path = ~/Library/Fonts/,
  Extension = .ttf,
  UprightFont = Lato-Regular,
  BoldFont = Lato-Bold,
  ItalicFont = Lato-Italic,
  BoldItalicFont = Lato-BoldItalic
]
```
- Regular font weight: 400 (Lato-Regular)
- Bold font weight: 700 (Lato-Bold)
- Note: Avoid `\input{glyphtounicode}` and `\pdfgentounicode=1` in XeTeX as they are pdfTeX-only primitives.

## 3. Mandatory Bolding Standard
Every tailored resume must visually pop under recruiter scanning. ChatGPT visual review strictly enforces bolding on:
1. **Quantified Metrics & Currency:**
   - `\textbf{94\% to 99.8\%}` (AWS Glue reliability)
   - `\textbf{\$300/day}` (operating cost savings)
   - `\textbf{\$5,000+/month}` (cross-AZ network transfer savings)
   - `\textbf{p95 latency under 600ms}` (conversational voice agent)
   - `\textbf{AIR <rank>}` (Nationwide engineering exam)
   - `\textbf{<rank> (<percentile> percentile)}` (Competitive entrance exam)
   - `\textbf{billions of records}`
   - `\textbf{650+ daily partner communications}`
   - `\textbf{100,000+ KAM notes}`
   - `\textbf{70\%+}` inference cost reduction
   - `\textbf{57\%}` manual audit reduction
   - `\textbf{INR 40 Lakh}` NRDC grant
   - `\textbf{97\% extraction accuracy}`, `\textbf{2$\times$ faster}`
   - `\textbf{6 F1 points}`, `\textbf{25,000+ relational entities}`, `\textbf{20\%}`
   - `\textbf{166 students}`
   - `\textbf{40\% MTTD}` across 5 test services
2. **Selective Technologies:**
   - `\textbf{Apache Spark}`, `\textbf{AWS Glue}`, `\textbf{Kafka CDC (Debezium)}`, `\textbf{Apache Hudi}`, `\textbf{Parquet}`, `\textbf{FastAPI}`, `\textbf{Docker}`, `\textbf{React}`, `\textbf{PyTorch}`, `\textbf{RAG}`, `\textbf{MCP}`, `\textbf{Athena}`.

## 4. Programmatic Verification Loop
1. **Compilation:**
   ```bash
   /opt/homebrew/bin/tectonic resume.tex
   ```
2. **Deterministic 1-Page Check (macOS PDFKit):**
   ```bash
   osascript -l JavaScript -e '
   ObjC.import("PDFKit");
   const doc = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(".../resume.pdf"));
   console.log("PDFKit Page Count:", doc.pageCount);
   '
   ```
   If `pageCount > 1`, auto-tune `linespread` to `0.96` and `itemsep` to `0.2pt`.
3. **Solid Opaque White-Background PNG Conversion:**
   Standard `sips` converts PDFs to transparent PNGs, causing black backgrounds and invisible text in dark-mode viewers like ChatGPT.
   We compile via `engine/pdf_to_image.swift`:
   ```bash
   swift engine/pdf_to_image.swift resume.pdf resume_white.png 2.5
   ```
4. **ChatGPT Visual Review Protocol:**
   Pass `resume_white.png` to ChatGPT in ego-browser Profile 1 with the criteria:
   - Criterion 1: One-page density (zero bottom whitespace)
   - Criterion 2: Margins and zero text collisions/overlaps
   - Criterion 3: Strong bolding on metrics and technologies
   - Criterion 4: Professional aesthetic & hierarchy
   - Require explicit verdict: `[APPROVED]`.
