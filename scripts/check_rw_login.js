(async () => {
  const task = await taskSpace('check_rw_login', { profileId: 'Profile 1' });
  const page = task.page('p1');
  await page.goto('https://resumeworded.com/account-login.php', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await new Promise(r => setTimeout(r, 3000));

  const info = await page.evaluate(() => {
    const googleBtn = document.querySelector('a[href*="google"], button[class*="google"], .g_id_signin, iframe[src*="google"]');
    const inputs = Array.from(document.querySelectorAll('input')).map(i => ({ name: i.name, type: i.type, id: i.id, placeholder: i.placeholder }));
    const buttons = Array.from(document.querySelectorAll('button, a.btn, input[type="submit"]')).map(b => b.innerText || b.value);
    return {
      hasGoogleBtn: !!googleBtn,
      googleBtnHTML: googleBtn ? googleBtn.outerHTML : null,
      inputs,
      buttons
    };
  });

  console.log('[*] Login page elements:');
  console.log(JSON.stringify(info, null, 2));
})();
