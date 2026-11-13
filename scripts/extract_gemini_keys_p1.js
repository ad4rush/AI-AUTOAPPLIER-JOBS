const fs = require('fs');

(async () => {
  const task = await taskSpace('get_gemini_p1');
  const page = task.page('p1');
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);

  const buttonTexts = ['be2A', '8bpY', 'zwoM', 'mb10', '2e90'];
  console.log('Target suffixes:', buttonTexts);

  const keys = [];
  for (const suf of buttonTexts) {
    console.log(`[*] Opening key with suffix ${suf}...`);
    await page.evaluate(s => {
      const btn = Array.from(document.querySelectorAll('button')).find(b => b.innerText.includes(s));
      if (btn) btn.click();
    }, suf);
    await page.waitForTimeout(1500);

    const keyVal = await page.evaluate(() => {
      const dialog = document.querySelector('dialog, [role="dialog"], .mat-mdc-dialog-container');
      if (!dialog) return null;
      const text = dialog.innerText;
      const m = text.match(/API Key\s*\n\s*([^\s\n]+)/);
      return m ? m[1] : null;
    });

    if (keyVal) {
      keys.push(keyVal);
      console.log(`Key for ${suf}:`, keyVal.slice(0, 14) + '...' + keyVal.slice(-6));
    }

    // Click close button inside dialog
    await page.evaluate(() => {
      const closeBtn = document.querySelector('dialog button, [role="dialog"] button');
      if (closeBtn) closeBtn.click();
    });
    await page.keyboard.press('Escape');
    await page.waitForTimeout(800);
  }

  const unique = Array.from(new Set(keys));
  console.log('Unique keys count:', unique.length);
  fs.writeFileSync('/tmp/gemini_keys_p1.json', JSON.stringify(unique, null, 2));
})();
