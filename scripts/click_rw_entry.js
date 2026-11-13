(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name.startsWith('rw_live_score_'));
  if (!s) {
    console.log('No rw_live_score space found');
    return;
  }
  console.log('[*] Resuming space:', s.name, s.id);
  const task = await taskSpace(s.id);
  const page = task.page('p1');

  console.log('[*] Current URL:', await page.url());

  // Click on Entry-level CHOOSE button
  console.log('[*] Clicking Entry-level CHOOSE button...');
  const clicked = await page.evaluate(() => {
    const btns = Array.from(document.querySelectorAll('a, button, div, span'));
    const entryChoose = btns.find(b => b.innerText.trim() === 'CHOOSE' || b.innerText.includes('Entry'));
    if (entryChoose) {
      entryChoose.click();
      return true;
    }
    return false;
  });
  console.log('[*] Click result:', clicked);

  await new Promise(r => setTimeout(r, 6000));
  console.log('[*] URL after click:', await page.url());
  console.log('[*] Title after click:', await page.title());

  const bodySnippet = await page.evaluate(() => document.body.innerText.slice(0, 1500));
  console.log('[*] Body text after click:');
  console.log(bodySnippet);

  // Check if email signup modal appeared
  const modalInfo = await page.evaluate(() => {
    const emailInput = document.querySelector('input[type="email"], #signup-email, input[name="email"]');
    const submitBtn = document.querySelector('button[type="submit"], input[type="submit"], .btn-signup');
    return {
      hasEmailInput: !!emailInput,
      emailId: emailInput ? emailInput.id : null,
      hasSubmitBtn: !!submitBtn
    };
  });
  console.log('[*] Modal info:', modalInfo);
})();
