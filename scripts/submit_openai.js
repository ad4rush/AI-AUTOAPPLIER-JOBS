(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === "ashby_auto_apply");
  if (!s) {
    console.log("No ashby_auto_apply space found");
    return;
  }
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  console.log("[*] Current page:", await page.url(), await page.title());

  const btnFound = await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim().toLowerCase().includes("submit application") || b.innerText.trim().toLowerCase() === "submit");
    if (!btn) return { found: false };
    return {
      found: true,
      text: btn.innerText.trim(),
      disabled: btn.disabled
    };
  });
  console.log("[*] Submit button on OpenAI:", JSON.stringify(btnFound));

  if (btnFound.found && !btnFound.disabled) {
    console.log("[*] Clicking submit button on OpenAI...");
    await page.evaluate(() => {
      const btn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim().toLowerCase().includes("submit application") || b.innerText.trim().toLowerCase() === "submit");
      btn.click();
    });
    console.log("[+] Click dispatched. Waiting 5s for submission confirmation...");
    await page.waitForTimeout(5000);
    const postTitle = await page.title();
    const postUrl = await page.url();
    console.log(`[+] Post-Submit Title: ${postTitle} | URL: ${postUrl}`);
  }
})();
