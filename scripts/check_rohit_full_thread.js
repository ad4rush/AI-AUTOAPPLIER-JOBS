(async () => {
  const task = await taskSpace('linkedin_rohit_check');
  const page = task.page('p1');

  const fullThread = await page.evaluate(() => {
    const list = Array.from(document.querySelectorAll('.msg-s-message-listitem, .msg-s-event-listitem'));
    return list.map(el => {
      const sender = el.querySelector('.msg-s-message-group__name, .msg-s-message-group__profile-link, .msg-s-message-group__meta')?.textContent?.trim() || '';
      const text = el.querySelector('.msg-s-event-listitem__body, .msg-s-message-listitem__body, p')?.innerText?.trim() || '';
      const time = el.querySelector('time')?.textContent?.trim() || '';
      return { sender, text, time };
    }).filter(m => m.text.length > 0);
  });

  console.log('[*] Full thread messages (count: ' + fullThread.length + '):');
  console.log(JSON.stringify(fullThread.slice(-10), null, 2));
})();
