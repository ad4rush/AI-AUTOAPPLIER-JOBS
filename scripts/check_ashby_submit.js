(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === "ashby_auto_apply");
  if (!s) return;
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  const state = await page.evaluate(() => {
    const text = document.body.innerText;
    const isSubmitted = text.includes("Thank you") || text.includes("Application Submitted") || text.includes("We have received your application") || text.includes("Success");
    const errors = Array.from(document.querySelectorAll("[aria-invalid='true'], .error, [class*='error']")).map(e => e.innerText || e.id);
    return {
      isSubmitted,
      title: document.title,
      url: window.location.href,
      bodySnippet: text.slice(0, 300),
      errors
    };
  });
  console.log("ASHBY STATE:", JSON.stringify(state, null, 2));
})();
