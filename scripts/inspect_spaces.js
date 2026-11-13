(async () => {
  const spaces = await listTaskSpaces();
  for (const sName of ["greenhouse_auto_apply", "ashby_auto_apply"]) {
    const s = spaces.find(x => x.name === sName);
    if (!s) continue;
    let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
    const page = task.page("p1");
    const title = await page.title();
    const url = await page.url();
    console.log(`[${sName}] Title: ${title} | URL: ${url}`);
  }
})();
