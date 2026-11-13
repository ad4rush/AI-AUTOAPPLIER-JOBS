(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === "greenhouse_auto_apply");
  if (!s) return;
  let task = s.ownership === "agent" ? await taskSpace(s.id) : await takeOverTaskSpace(s.id);
  const page = task.page("p1");

  const qDetails = await page.evaluate(() => {
    const errorIds = [
      "question_15797027008",
      "question_15797030008",
      "question_15797031008",
      "question_15797036008",
      "question_15797038008",
      "question_18372122008",
      "question_18374786008"
    ];
    return errorIds.map(id => {
      const el = document.getElementById(id);
      if (!el) return { id, missing: true };
      const label = el.closest(".field")?.querySelector("label")?.innerText || document.querySelector("label[for='" + id + "']")?.innerText;
      return {
        id,
        tag: el.tagName,
        type: el.type,
        label: label ? label.trim() : "",
        html: el.closest(".field")?.innerHTML.slice(0, 300)
      };
    });
  });
  console.log("ANTHROPIC QUESTIONS:\n", JSON.stringify(qDetails, null, 2));
})();
