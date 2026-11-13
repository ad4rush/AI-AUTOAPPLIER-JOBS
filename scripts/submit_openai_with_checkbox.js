(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === "ashby_auto_apply");
  if (!s) return;
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  console.log("[*] Checking acknowledgment checkbox...");
  const checkRes = await page.evaluate(() => {
    const checkboxes = Array.from(document.querySelectorAll("input[type='checkbox']"));
    const results = [];
    for (const cb of checkboxes) {
      if (!cb.checked) {
        cb.click();
        cb.checked = true;
        cb.dispatchEvent(new Event("change", { bubbles: true }));
        results.push("Checked: " + (cb.id || cb.name || "unnamed"));
      }
    }
    return results;
  });
  console.log("Checkboxes:", checkRes);

  await page.waitForTimeout(500);

  // Click Submit
  console.log("[*] Clicking Submit Application...");
  await page.evaluate(() => {
    const btn = Array.from(document.querySelectorAll("button")).find(b => b.innerText.trim().toLowerCase().includes("submit application") || b.innerText.trim().toLowerCase() === "submit");
    if (btn) btn.click();
  });

  await page.waitForTimeout(6000);
  const finalState = await page.evaluate(() => {
    return {
      title: document.title,
      url: window.location.href,
      text: document.body.innerText.slice(0, 400)
    };
  });

  console.log("FINAL STATE AFTER SUBMIT:\n", JSON.stringify(finalState, null, 2));
})();
