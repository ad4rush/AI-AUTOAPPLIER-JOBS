(async () => {
  const spaces = await listTaskSpaces();
  const s = spaces.find(x => x.name.startsWith('rw_live_score_'));
  const task = await taskSpace(s.id);
  const page = task.page('p1');

  console.log('[*] Clicking Sign in with Google button...');
  await page.evaluate(() => {
    const googleBtn = document.querySelector('[aria-labelledby="button-label"], .g_id_signin, [class*="nsm7Bb"]');
    if (googleBtn) googleBtn.click();
    else {
      const span = Array.from(document.querySelectorAll('span')).find(s => s.innerText.includes('Sign in with Google'));
      if (span) span.click();
    }
  });

  console.log('[*] Clicked Google button. Waiting 10 seconds for SSO and redirect...');
  for (let i = 0; i < 10; i++) {
    await new Promise(r => setTimeout(r, 2000));
    const url = await page.url();
    const title = await page.title();
    console.log(`[Wait ${(i + 1) * 2}s] Title: ${title} | URL: ${url}`);
    if (url.includes('results-v2.php') || url.includes('score')) {
      break;
    }
  }

  const scoreData = await page.evaluate(() => {
    const text = document.body.innerText;
    const overallMatch = text.match(/Your resume scored\s+(\d+)\s+out of 100/i) || text.match(/(\d+)\s+OVERALL/i) || text.match(/(\d+)\s*\/100/);
    const brevityMatch = text.match(/Brevity\s*(\d+)\/100/i) || text.match(/Brevity[^\d]+(\d+)/i);
    const impactMatch = text.match(/Impact\s*(\d+)\/100/i) || text.match(/Impact[^\d]+(\d+)/i);
    const styleMatch = text.match(/Style\s*(\d+)\/100/i) || text.match(/Style[^\d]+(\d+)/i);
    const sectionsMatch = text.match(/Sections\s*(\d+)\/100/i) || text.match(/Sections[^\d]+(\d+)/i);

    return {
      title: document.title,
      url: window.location.href,
      overallScore: overallMatch ? overallMatch[1] : null,
      subscores: {
        brevity: brevityMatch ? brevityMatch[1] : null,
        impact: impactMatch ? impactMatch[1] : null,
        style: styleMatch ? styleMatch[1] : null,
        sections: sectionsMatch ? sectionsMatch[1] : null
      },
      textSnippet: text.slice(0, 1500)
    };
  });

  console.log('[*] Score data extracted:');
  console.log(JSON.stringify(scoreData, null, 2));

  const fs = require('fs');
  fs.writeFileSync('./data/rw_live_result.json', JSON.stringify(scoreData, null, 2), 'utf8');
})();
