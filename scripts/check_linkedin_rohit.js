(async () => {
  const task = await taskSpace('linkedin_rohit_check');
  const page = task.page('p1');
  console.log('[*] Connected to page. URL:', await page.url());

  const info = await page.evaluate(() => {
    // Current active thread header
    const activeHeader = document.querySelector('.msg-entity-lockup__entity-title, .msg-title-bar__title, [class*="active-thread"]')?.textContent?.trim();

    // Messages in the active thread
    const messageElements = Array.from(document.querySelectorAll('.msg-s-message-listitem, [class*="msg-s-event-listitem"]'));
    const messages = messageElements.map(el => {
      const sender = el.querySelector('.msg-s-message-group__name, .msg-s-message-group__profile-link')?.textContent?.trim() || 'unknown';
      const body = el.querySelector('.msg-s-event-listitem__body, .msg-s-message-listitem__body')?.textContent?.trim() || el.innerText;
      return { sender, body };
    });

    // Sidebar conversation list
    const sidebarItems = Array.from(document.querySelectorAll('.msg-conversation-listitem, .msg-conversation-card, li[class*="msg-conversation"]'));
    const convos = sidebarItems.map(el => {
      const name = el.querySelector('.msg-conversation-listitem__participant-names, .msg-conversation-card__participant-names, [class*="participant-name"]')?.textContent?.trim();
      const snippet = el.querySelector('.msg-conversation-card__message-snippet, .msg-conversation-listitem__message-snippet, [class*="message-snippet"]')?.textContent?.trim();
      return { name, snippet };
    });

    return { activeHeader, messagesCount: messages.length, recentMessages: messages.slice(-5), convos: convos.slice(0, 15) };
  });

  console.log('[*] Extracted LinkedIn info:');
  console.log(JSON.stringify(info, null, 2));
})();
