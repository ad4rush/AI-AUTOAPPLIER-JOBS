const fs = require('fs');

(async () => {
  const task = await taskSpace('get_gemini_p2', { profileId: 'Profile 2' });
  const page = task.page('p1');
  console.log('[*] Navigating Profile 2 to AI Studio...');
  await page.goto('https://aistudio.google.com/app/api-keys', { waitUntil: 'domcontentloaded', timeout: 35000 });
  await page.waitForTimeout(4000);
  console.log('Profile 2 Title:', await page.title());
  console.log('Profile 2 URL:', await page.url());

  const rowCount = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('tr, [role="row"]')).filter(r => r.innerText.includes('...'));
    return rows.length;
  });
  console.log('Profile 2 Row count:', rowCount);

  const keys = [];
  for (let i = 0; i < rowCount; i++) {
    await page.evaluate(idx => {
      const rows = Array.from(document.querySelectorAll('tr, [role="row"]')).filter(r => r.innerText.includes('...'));
      const btn = rows[idx] ? rows[idx].querySelector('button') : null;
      if (btn) btn.click();
    }, i);
    await page.waitForTimeout(1200);

    const keyVal = await page.evaluate(() => {
      const dialog = document.querySelector('dialog, [role="dialog"], .mat-mdc-dialog-container');
      if (!dialog) return null;
      const text = dialog.innerText;
      const m = text.match(/API Key\s*\n\s*([^\s\n]+)/);
      return m ? m[1] : null;
    });

    if (keyVal) {
      keys.push(keyVal);
      console.log('P2 Key ' + i + ':', keyVal.slice(0, 12) + '...' + keyVal.slice(-6));
    }

    await page.keyboard.press('Escape');
    await page.waitForTimeout(600);
  }

  const unique = Array.from(new Set(keys));
  console.log('Profile 2 Unique keys count:', unique.length);
  fs.writeFileSync('/tmp/gemini_keys_p2.json', JSON.stringify(unique, null, 2));
})();
