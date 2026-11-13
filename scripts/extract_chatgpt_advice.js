(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name === 'chatgpt_google_advisor');
  if (!s) {
    console.log('Task space not found');
    return;
  }
  const task = await taskSpace(s.id);
  const page = task.page('p1');
  const text = await page.evaluate(() => document.body.innerText);
  console.log('[*] Full page text length:', text.length);
  // Find where the assistant message starts
  const idx = text.indexOf('You said:');
  if (idx !== -1) {
    const afterYouSaid = text.slice(idx);
    const gptIdx = afterYouSaid.indexOf('ChatGPT said:');
    if (gptIdx !== -1) {
      console.log('[*] ChatGPT said:');
      console.log(afterYouSaid.slice(gptIdx, gptIdx + 4000));
      const fs = require('fs');
      fs.writeFileSync('./data/chatgpt_google_advice_full.txt', afterYouSaid.slice(gptIdx), 'utf8');
    } else {
      console.log('[*] Still thinking or generating...');
      console.log(afterYouSaid.slice(-1000));
    }
  }
})();
