(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === "greenhouse_auto_apply");
  if (!s) return;
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  console.log("[*] Current page:", await page.url(), await page.title());

  const btn = await page.evaluate(() => {
    const b = Array.from(document.querySelectorAll("button, input[type='submit']")).find(el => (el.innerText || el.value || "").toLowerCase().includes("submit"));
    return b ? { found: true, text: b.innerText || b.value, disabled: b.disabled, id: b.id } : { found: false };
  });
  console.log("Submit button on Anthropic:", JSON.stringify(btn));

  if (btn.found && !btn.disabled) {
    console.log("[*] Clicking Submit Application on Anthropic...");
    await page.evaluate(() => {
      const b = Array.from(document.querySelectorAll("button, input[type='submit']")).find(el => (el.innerText || el.value || "").toLowerCase().includes("submit"));
      b.click();
    });
    await page.waitForTimeout(6000);
    const postState = await page.evaluate(() => {
      return {
        title: document.title,
        url: window.location.href,
        bodySnippet: document.body.innerText.slice(0, 400),
        errors: Array.from(document.querySelectorAll(".label--error, .field--error, [aria-invalid='true']")).map(e => e.innerText || e.id)
      };
    });
    console.log("POST SUBMIT ANTHROPIC:\n", JSON.stringify(postState, null, 2));
  }
})();
