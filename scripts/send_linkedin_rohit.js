(async () => {
  const task = await taskSpace('linkedin_rohit_check');
  const page = task.page('p1');

  const messageText = process.argv[2] || `Sharing my portfolio and resume link for quick reference: ${process.env.CANDIDATE_PORTFOLIO || ""}`;

  console.log('[*] Focusing contenteditable editor...');
  await page.evaluate((text) => {
    const editor = document.querySelector('.msg-form__contenteditable, [contenteditable="true"]');
    if (!editor) throw new Error('Editor not found');
    editor.focus();
    // Use document.execCommand to trigger LinkedIn's internal draft state bindings
    document.execCommand('insertText', false, text);
  }, messageText);

  await page.waitForTimeout(1000);

  // Check send button status
  const btnState = await page.evaluate(() => {
    const btn = document.querySelector('.msg-form__send-button, button.msg-form__send-button');
    return { disabled: btn ? btn.disabled : true, text: btn ? btn.innerText : null };
  });

  console.log('[*] Send button state after typing:', btnState);

  if (!btnState.disabled) {
    console.log('[*] Clicking Send button...');
    await page.evaluate(() => {
      const btn = document.querySelector('.msg-form__send-button, button.msg-form__send-button');
      btn.click();
    });
    await page.waitForTimeout(3000);
    console.log('[✓] Message sent successfully!');
  } else {
    console.log('[!] Send button is still disabled, trying keyboard shortcut (Cmd+Enter / Enter)...');
    await page.keyboard.press('Meta+Enter');
    await page.waitForTimeout(3000);
  }

  // Verify recent messages in thread
  const lastMsg = await page.evaluate(() => {
    const msgs = Array.from(document.querySelectorAll('.msg-s-event-listitem__body, .msg-s-message-listitem__body, p'));
    return msgs.length > 0 ? msgs[msgs.length - 1].innerText : null;
  });

  console.log('[*] Latest message in thread now:', lastMsg);
})();
