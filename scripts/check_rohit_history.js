(async () => {
  const task = await taskSpace('linkedin_rohit_check');
  const page = task.page('p1');

  const history = await page.evaluate(() => {
    const list = Array.from(document.querySelectorAll('.msg-s-message-listitem, [class*="msg-s-event-listitem"]'));
    return list.slice(-10).map(el => {
      const author = el.querySelector('.msg-s-message-group__name, .msg-s-message-group__profile-link, [class*="sender-name"]')?.textContent?.trim();
      const text = el.querySelector('.msg-s-event-listitem__body, .msg-s-message-listitem__body, p')?.innerText?.trim();
      const time = el.querySelector('time')?.textContent?.trim();
      return { author, text, time };
    });
  });

  console.log('[*] Rohit conversation history:');
  console.log(JSON.stringify(history, null, 2));
})();
