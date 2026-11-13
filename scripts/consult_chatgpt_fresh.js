(async () => {
  const task = await taskSpace('chatgpt_google_fresh', { profileId: 'Profile 1' });
  const page = task.page('p1');
  console.log('[*] Navigating to fresh ChatGPT session in Profile 1...');
  await page.goto('https://chatgpt.com/', { waitUntil: 'domcontentloaded', timeout: 35000 });
  await new Promise(r => setTimeout(r, 4000));

  console.log('[*] Page title:', await page.title());

  const promptText = process.argv[2] || `You are an expert tech hiring manager and technical bar-raiser.
Evaluate this candidate for target engineering roles based on their verified master profile.
Highlight strengths, key architectural accomplishments, and exact bullet adjustments using the Google XYZ formula: 'Accomplished [X] as measured by [Y], by doing [Z]'.`;

  // Focus prompt textarea
  console.log('[*] Entering prompt into ChatGPT composer...');
  await page.evaluate((text) => {
    const editor = document.querySelector('#prompt-textarea, [contenteditable="true"], textarea');
    if (!editor) throw new Error('Composer textarea not found');
    editor.focus();
    if (editor.tagName === 'TEXTAREA') {
      editor.value = text;
      editor.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
      document.execCommand('insertText', false, text);
    }
  }, promptText);

  await new Promise(r => setTimeout(r, 1500));

  // Click Send button
  console.log('[*] Clicking Send button...');
  await page.evaluate(() => {
    const btn = document.querySelector('button[data-testid="send-button"], button[aria-label="Send prompt"]');
    if (btn) btn.click();
    else {
      // Try Enter key
      const editor = document.querySelector('#prompt-textarea, [contenteditable="true"], textarea');
      editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    }
  });

  console.log('[*] Sent prompt! Waiting 20 seconds for response generation...');
  await new Promise(r => setTimeout(r, 20000));

  // Extract response
  const reply = await page.evaluate(() => {
    const articles = document.querySelectorAll('article, [data-message-author-role="assistant"]');
    if (articles.length === 0) return document.body.innerText;
    return articles[articles.length - 1].innerText;
  });

  console.log('[*] ChatGPT Response snippet:');
  console.log(reply.slice(0, 2000));

  const fs = require('fs');
  fs.writeFileSync('./data/chatgpt_google_fresh_opinion.txt', reply, 'utf8');
  console.log('[✓] Wrote full opinion to ./data/chatgpt_google_fresh_opinion.txt');
})();
