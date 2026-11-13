(async () => {
  const task = await taskSpace('get_gemini_p1');
  const page = task.page('p1');
  await page.goto('https://aistudio.google.com/app/api-keys', { waitUntil: 'domcontentloaded', timeout: 35000 });
  await page.waitForTimeout(3000);

  const rowDetails = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tr, [role="row"]')).filter(r => r.innerText.includes('...'));
    return rows.map((r, idx) => {
      const btns = Array.from(r.querySelectorAll('button')).map(b => ({
        text: b.innerText.trim(),
        ariaLabel: b.getAttribute('aria-label'),
        title: b.getAttribute('title')
      }));
      return { idx, btns };
    });
  });
  console.log('Row details:', JSON.stringify(rowDetails, null, 2));
})();
