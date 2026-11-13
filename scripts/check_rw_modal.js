(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name.startsWith('rw_live_score_'));
  const task = await taskSpace(s.id);
  const page = task.page('p1');

  const modalDetails = await page.evaluate(() => {
    const modal = document.querySelector('.modal, [role="dialog"], .jquery-modal, form');
    const googleBtn = document.querySelector('iframe[src*="google"], .g_id_signin, [class*="google"]');
    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"])')).map(i => ({
      id: i.id,
      name: i.name,
      type: i.type,
      placeholder: i.placeholder,
      visible: i.offsetParent !== null
    }));
    return {
      hasGoogleBtn: !!googleBtn,
      googleBtnHTML: googleBtn ? googleBtn.outerHTML : null,
      inputs
    };
  });

  console.log('[*] Modal details:');
  console.log(JSON.stringify(modalDetails, null, 2));
})();
