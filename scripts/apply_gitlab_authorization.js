(async () => {
  const spaces = await listTaskSpaces();
  let s = spaces.find(x => x.name === "gitlab_auth_apply");
  if (!s) {
    console.log("[!] Creating gitlab_auth_apply task space...");
    s = await taskSpace("gitlab_auth_apply", { profileId: "Profile 1" });
  }
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  const url = "https://job-boards.greenhouse.io/gitlab/jobs/8905402002";
  if ((await page.url()) !== url) {
    console.log("[*] Navigating to", url);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 35000 });
    await page.waitForTimeout(3000);
  }

  // Helper to click select option by text
  async function chooseSelectOption(inputId, targetText) {
    console.log(`[*] Selecting '${targetText}' on #${inputId}...`);
    await page.evaluate(id => {
      const el = document.getElementById(id);
      const ctrl = el?.closest('.select__control') || el;
      if (ctrl) ctrl.scrollIntoView({ behavior: 'instant', block: 'center' });
    }, inputId);
    await page.waitForTimeout(200);
    await page.focus("#" + inputId);
    await page.keyboard.press("ArrowDown");
    await page.waitForTimeout(400);

    const selectedText = await page.evaluate((args) => {
      const { id, target } = args;
      const listbox = document.getElementById(`react-select-${id}-listbox`) || document.querySelector(`[role='listbox']:not([id^='iti-'])`);
      if (!listbox) return null;
      const opts = Array.from(listbox.querySelectorAll(`[role='option'], .select__option`));
      const filtered = opts.filter(o => !o.id.startsWith("iti-"));
      let match = filtered.find(o => o.innerText.trim().toLowerCase() === target.toLowerCase());
      if (!match) match = filtered.find(o => o.innerText.trim().toLowerCase().startsWith(target.toLowerCase()));
      if (!match) match = filtered.find(o => o.innerText.trim().toLowerCase().includes(target.toLowerCase()));
      if (match) {
        match.click();
        return match.innerText.trim();
      }
      return null;
    }, { id: inputId, target: targetText });

    if (selectedText) {
      console.log(`[+] Clicked option '${selectedText}' for #${inputId}`);
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

  console.log("[*] Filling standard fields on GitLab Authorization...");
  // 1. Basic Info
  await setFieldValue("first_name", process.env.CANDIDATE_FIRST_NAME || "");
  await setFieldValue("last_name", process.env.CANDIDATE_LAST_NAME || "");
  await setFieldValue("email", process.env.CANDIDATE_COLLEGE_EMAIL || process.env.CANDIDATE_EMAIL || "");

  // Phone
  await chooseSelectOption("country", "India");
  await setFieldValue("phone", process.env.CANDIDATE_PHONE_PLAIN || "");

  // Location
  console.log("[*] Filling candidate-location...");
  await page.evaluate(() => {
    const el = document.getElementById("candidate-location");
    el?.closest('.select__control')?.scrollIntoView({ behavior: 'instant', block: 'center' });
  });
  await page.focus("#candidate-location");
  await page.keyboard.type("Bengaluru");
  await page.waitForTimeout(600);
  const locOpt = await page.evaluate(() => {
    const opts = Array.from(document.querySelectorAll("[id*='react-select-candidate-location-option-'], .select__option"));
    if (opts.length > 0) {
      opts[0].click();
      return opts[0].innerText.trim();
    }
    return null;
  });
  console.log("[+] Location selected:", locOpt);
  await page.waitForTimeout(400);

  // Resume Upload
  const resumePath = "./master_resumes/RESUME_3_SWE_BACKEND.pdf";
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
  await setFieldValue("question_38903310002", process.env.CANDIDATE_LINKEDIN || "");
  await setFieldValue("question_38903311002", process.env.CANDIDATE_FIRST_NAME || "");

  // Country of residence -> India
  await chooseSelectOption("question_38903312002", "India");

  await chooseSelectOption("question_38903313002", "No"); // employment restrictions
  await setFieldValue("question_38903315002", process.env.CANDIDATE_GITHUB_USERNAME || process.env.CANDIDATE_USERNAME || ""); // gitlab username
  await chooseSelectOption("question_38903316002", "No"); // sponsorship
  await chooseSelectOption("question_38903317002", "No"); // previous gitlab work

  // Ruby on rails textarea
  console.log("[*] Filling Ruby on Rails textarea...");
  const rubyAnswer = `In my backend systems engineering work, I have designed and maintained production services following robust MVC and clean architecture principles. At TBO.com and in enterprise platforms, I work daily with high-throughput API design, relational schema migrations, and asynchronous background worker queues. I have built and maintained services with ActiveRecord/PostgreSQL, configured transactional boundaries and isolation levels, integrated Redis-backed job queues (Sidekiq) for asynchronous execution, and written automated unit and integration test suites (RSpec). Furthermore, I have architected secure API gateways ensuring low-latency request lifecycle management, structured error handling, and robust data integrity across distributed microservices.`;
  await setFieldValue("question_39083668002", rubyAnswer);
  await page.waitForTimeout(400);

  // Authorization concepts -> Yes
  await chooseSelectOption("question_39083669002", "Yes");

  // Full-time experience -> 0 - 2 years
  await chooseSelectOption("question_39125704002", "0 - 2 years");

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
