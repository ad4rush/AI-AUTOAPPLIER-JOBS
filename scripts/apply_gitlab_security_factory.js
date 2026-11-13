const { execSync } = require('child_process');

(async () => {
  const spaces = await listTaskSpaces();
  let s = spaces.find(x => x.name === "gitlab_apply") || spaces.find(x => x.id === 512);
  if (!s) {
    console.log("[!] Creating gitlab_apply task space...");
    s = await taskSpace("gitlab_apply", { profileId: "Profile 1" });
  }
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  const url = "https://job-boards.greenhouse.io/gitlab/jobs/8890971002";
  if ((await page.url()) !== url) {
    console.log("[*] Navigating to", url);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 35000 });
    await page.waitForTimeout(3000);
  }

  // Helper to click select option by text
  async function chooseSelectOption(inputId, targetText) {
    console.log(`[*] Selecting '${targetText}' on #${inputId}...`);
    await page.click("#" + inputId);
    await page.waitForTimeout(300);
    await page.press("#" + inputId, "ArrowDown");
    await page.waitForTimeout(400);

    const optionId = await page.evaluate((args) => {
      const { id, target } = args;
      const opts = Array.from(document.querySelectorAll(`[id*='react-select-${id}-option-'], .select__option, [role='option']`));
      const filtered = opts.filter(o => !o.id.startsWith("iti-"));
      let match = filtered.find(o => o.innerText.trim().toLowerCase() === target.toLowerCase());
      if (!match) match = filtered.find(o => o.innerText.trim().toLowerCase().startsWith(target.toLowerCase()));
      if (!match) match = filtered.find(o => o.innerText.trim().toLowerCase().includes(target.toLowerCase()));
      return match ? match.id : null;
    }, { id: inputId, target: targetText });

    if (optionId) {
      await page.click("#" + optionId);
      console.log(`[+] Clicked option #${optionId} for #${inputId}`);
      await page.waitForTimeout(300);
      return true;
    } else {
      console.log(`[!] Option '${targetText}' not found for #${inputId}`);
      return false;
    }
  }

  function setFieldValue(id, val) {
    return page.evaluate(({ id, val }) => {
      const el = document.getElementById(id);
      if (!el) return false;
      const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, val);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      el.dispatchEvent(new Event('blur', { bubbles: true }));
      return true;
    }, { id, val });
  }

  console.log("[*] Filling standard fields...");
  // 1. Basic Info
  await setFieldValue("first_name", process.env.CANDIDATE_FIRST_NAME || "");
  await setFieldValue("last_name", process.env.CANDIDATE_LAST_NAME || "");
  await setFieldValue("email", process.env.CANDIDATE_COLLEGE_EMAIL || process.env.CANDIDATE_EMAIL || "");

  // Phone
  await chooseSelectOption("country", "India");
  await setFieldValue("phone", process.env.CANDIDATE_PHONE_PLAIN || "");

  // Location
  console.log("[*] Filling candidate-location...");
  await page.click("#candidate-location");
  await page.fill("#candidate-location", "Bengaluru");
  await page.waitForTimeout(600);
  const locOpt = await page.evaluate(() => {
    const opts = Array.from(document.querySelectorAll("[id*='react-select-candidate-location-option-'], .select__option"));
    return opts.length > 0 ? opts[0].id : null;
  });
  if (locOpt) {
    await page.click("#" + locOpt);
    console.log("[+] Selected location option:", locOpt);
  } else {
    await page.press("#candidate-location", "Enter");
  }
  await page.waitForTimeout(400);

  // Resume Upload
  const resumePath = "./resumes_generated/gitlab_gh_gitlab_8890971002/resume_gitlab_gh_gitlab_8890971002.pdf";
  const resumeAttached = await page.evaluate(() => {
    return !!document.querySelector('.file-upload__filename');
  });
  if (!resumeAttached) {
    console.log("[*] Attaching tailored resume:", resumePath);
    try {
      await page.setInputFiles("input#resume", resumePath);
      await page.waitForTimeout(2000);
    } catch(err) {
      console.log("[!] Resume attach error:", err.message);
    }
  } else {
    console.log("[+] Resume already attached.");
  }

  // Additional questions
  await setFieldValue("question_38808548002", process.env.CANDIDATE_LINKEDIN || "");
  await setFieldValue("question_38808549002", process.env.CANDIDATE_FIRST_NAME || "");
  await chooseSelectOption("question_38808550002", "No"); // employment restrictions
  await setFieldValue("question_38808552002", process.env.CANDIDATE_GITHUB_USERNAME || process.env.CANDIDATE_USERNAME || ""); // gitlab username
  await chooseSelectOption("question_38808553002", "No"); // sponsorship
  await chooseSelectOption("question_38808554002", "No"); // previous gitlab work

  // Country of residence -> India
  await page.click("#question_38808555002");
  await page.fill("#question_38808555002", "India");
  await page.waitForTimeout(500);
  const indiaOpt = await page.evaluate(() => {
    const opts = Array.from(document.querySelectorAll("[id*='react-select-question_38808555002-option-'], .select__option"));
    const match = opts.find(o => o.innerText.trim() === "India");
    return match ? match.id : (opts.length > 0 ? opts[0].id : null);
  });
  if (indiaOpt) {
    await page.click("#" + indiaOpt);
    console.log("[+] Selected country:", indiaOpt);
  }
  await page.waitForTimeout(400);

  // Relocate to Bangalore -> Yes
  await chooseSelectOption("question_39142260002", "Yes");

  // Experience
  await page.click("#question_39142261002");
  await page.waitForTimeout(300);
  await page.press("#question_39142261002", "ArrowDown");
  await page.waitForTimeout(400);
  const expOpts = await page.evaluate(() => {
    const opts = Array.from(document.querySelectorAll("[id*='react-select-question_39142261002-option-'], .select__option"));
    return opts.map(o => ({ id: o.id, text: o.innerText.trim() }));
  });
  const chosenExp = expOpts.find(o => o.text.includes("0 - 2") || o.text.includes("0-2") || o.text.includes("1") || o.text.includes("2")) || expOpts[0];
  if (chosenExp) {
    await page.click("#" + chosenExp.id);
    console.log("[+] Selected experience option:", chosenExp);
  }
  await page.waitForTimeout(400);

  // Static Analysis Textarea
  console.log("[*] Filling static analysis textarea...");
  const staticAnswer = `At TBO.com and in production systems engineering, my work across parsers, static analysis, and security scanning includes:

1. Parsers & AST Validation:
- Ontology-Grounded Text-to-SQL Agent: Engineered an enterprise schema-aware SQL validator on Amazon Athena. The system parses and validates SQL Abstract Syntax Trees (ASTs) against an enterprise travel domain ontology and catalog schemas prior to execution, preventing semantic hallucinations and unauthorized cross-table joins while cutting BI workload by 35%.
- Custom Linux Shell: Developed a Unix shell in C with a custom lexer/tokenizer and grammar parser handling pipe redirections, command chains, POSIX signal traps, and background process scheduling.
- LaTeX AST & Typographic Linter: Built an AST-based LaTeX sanitizer (Python) that parses token streams, resolves package/fontspec macro conflicts, disables problematic ligature encodings, and enforces strict single-page geometry constraints.

2. Static Analysis, Linters & CI/CD Security Scanning:
- Automated Security Gates: Integrated Bandit (AST-based Python vulnerability scanner) and flake8 into GitHub Actions CI/CD pipelines across microservices to enforce strict code quality and detect insecure patterns (e.g., hardcoded credentials, unsafe deserialization).
- Dependency Scanning (SCA & SBOM): Implemented automated Software Composition Analysis using pip-audit and safety against the PyPA/OSV advisory databases to flag vulnerable transitive dependencies before production deployments. Integrated container scanning with Trivy to inspect Docker base image layers and generate SBOM reports.
- Kafka CDC Payload Schema Validation: Enforced strict schema registry parsing and backward-compatible Debezium CDC ingestion in Apache Kafka/Glue pipelines across billions of records, preventing poison-pill schema mutations.`;

  await setFieldValue("question_39142262002", staticAnswer);
  await page.waitForTimeout(500);

  // Gender & Demographics
  try {
    await chooseSelectOption("gender", "Male");
    await chooseSelectOption("veteran_status", "I am not a protected veteran");
  } catch(e) {}

  await page.waitForTimeout(1000);

  // Final check of error fields & submit button
  const validation = await page.evaluate(() => {
    const errorLabels = Array.from(document.querySelectorAll(".label--error, [aria-invalid='true'], .error")).map(e => e.innerText ? e.innerText.trim() : e.id).filter(Boolean);
    const submitBtn = Array.from(document.querySelectorAll("button, input[type='submit']")).find(b => (b.innerText || b.value || "").toLowerCase().includes("submit"));
    return {
      errorCount: errorLabels.length,
      errors: errorLabels,
      submitBtnFound: !!submitBtn,
      submitBtnEnabled: submitBtn ? !submitBtn.disabled : false
    };
  });

  console.log("FINAL VALIDATION REPORT:\n", JSON.stringify(validation, null, 2));

  // If ready, click Submit!
  if (validation.submitBtnFound && validation.submitBtnEnabled && validation.errorCount === 0) {
    console.log("[*] Clicking Submit application...");
    await page.click("button[type='submit'], input[type='submit']");
    await page.waitForTimeout(7000);
    console.log("[+] Post-submit URL:", await page.url());
    console.log("[+] Post-submit Title:", await page.title());
    const bodySnippet = await page.evaluate(() => document.body.innerText.slice(0, 300));
    console.log("[+] Body snippet:\n", bodySnippet);
  } else {
    console.log("[!] Cannot submit yet due to errors or missing button.");
  }
})();
