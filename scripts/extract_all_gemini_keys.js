const fs = require('fs');

async function extractKeysFromProfile(profileId, spaceName) {
  console.log(`\n[*] Checking profile: ${profileId}...`);
  const spaces = await listTaskSpaces();
  let s = spaces.find(x => x.name === spaceName);
  let task = s ? await taskSpace(s.id) : await taskSpace(spaceName, { profileId: profileId });
  const page = task.page('p1');

  await page.goto('https://aistudio.google.com/app/api-keys', { waitUntil: 'domcontentloaded', timeout: 35000 });
  await page.waitForTimeout(4000);

  const title = await page.title();
  const url = await page.url();
  console.log(`[+] Page Title: ${title} | URL: ${url}`);

  if (!url.includes('api-keys')) {
    console.log(`[!] Not on api-keys page (might not be signed in or redirected).`);
    return [];
  }

  const count = await page.evaluate(() => document.querySelectorAll('.key-string-link').length);
  console.log(`[+] Found ${count} key links in profile ${profileId}`);

  const keys = [];
  for (let i = 0; i < count; i++) {
    // Click key link
    await page.evaluate(idx => {
      const el = document.querySelectorAll('.key-string-link')[idx];
      if (el) el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    }, i);
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
      console.log(`[+] Profile ${profileId} Key ${i + 1}: ${keyVal.slice(0, 12)}...${keyVal.slice(-6)}`);
    }

    // Close dialog
    await page.evaluate(() => {
      const dialog = document.querySelector('dialog, [role="dialog"], .mat-mdc-dialog-container');
      const closeBtn = dialog ? dialog.querySelector('button') : null;
      if (closeBtn) closeBtn.click();
    });
    await page.waitForTimeout(800);
  }

  return keys;
}

(async () => {
  const p1Keys = await extractKeysFromProfile('Profile 1', 'get_gemini_p1');
  let p2Keys = [];
  try {
    p2Keys = await extractKeysFromProfile('Profile 2', 'get_gemini_p2');
  } catch(e) {
    console.log('[!] Profile 2 check error:', e.message);
  }

  const allKeys = Array.from(new Set([...p1Keys, ...p2Keys]));
  console.log(`\n[=== EXTRACTION COMPLETE ===]`);
  console.log(`Total unique Gemini API keys retrieved: ${allKeys.length}`);
  fs.writeFileSync('./data/extracted_gemini_keys.json', JSON.stringify(allKeys, null, 2));
})();
